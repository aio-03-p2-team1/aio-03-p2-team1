import asyncio
import sqlite3
from types import SimpleNamespace
from pathlib import Path

import httpx
import pytest

from scripts.init_kinds import (
    SqliteSink,
    fetch_all,
    normalize,
    normalize_record,
    parse_items,
    require_api_key,
)


def test_parse_api_response_object_and_list():
    total, items = parse_items({"response": {"header": {"resultCode": "00"}, "body": {
        "totalCount": 1, "items": {"item": {"kind_cd": "001", "KNm": "골든 리트리버"}}
    }}})
    assert total == 1
    assert items[0]["kind_cd"] == "001"
    assert parse_items({"response": {"body": {"totalCount": 0, "items": ""}}}) == (0, [])


def test_search_normalization_ignores_whitespace():
    assert normalize("골든 리트리버") == normalize("골든리트리버")


def test_sqlite_sync_upserts_and_preserves_removed_codes(tmp_path):
    sink = SqliteSink(str(tmp_path / "kinds.sqlite"))
    now = "2026-11-16T00:00:00+00:00"
    record = normalize_record("dog", {"kind_cd": "001", "KNm": "골든 리트리버"}, now)
    sink.sync([record])
    sink.sync([record])
    rows = sink.db.execute("select species,kind_code,name,search_name,active from kinds").fetchall()
    aliases = sink.db.execute("select alias,search_alias from kind_aliases").fetchall()
    assert rows == [("dog", "001", "골든 리트리버", "골든리트리버", 1)]
    assert aliases == []  # 공백 표기 차이는 kind_aliases가 아닌 kinds.search_name으로 통합
    sink.sync([])  # caller disallows empty API payload; direct check status behavior
    assert sink.db.execute("select active from kinds where kind_code='001'").fetchone() == (0,)
    sink.close()


def test_sqlite_schema_has_search_indexes_and_foreign_key():
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys=ON")
    bootstrap = Path("scripts/bootstrap_schema.sql").read_text(encoding="utf-8")
    db.executescript(bootstrap)
    db.executescript(bootstrap)
    db.execute("insert into kinds(species,kind_code,name,search_name,created_at,updated_at) values('dog','001','믹스견','믹스견','x','x')")
    plan = db.execute("EXPLAIN QUERY PLAN SELECT kind_code FROM kinds WHERE species=? AND search_name=?", ("dog", "골든리트리버")).fetchone()[3]
    assert "kinds_search_name_idx" in plan
    try:
        db.execute("insert into kind_aliases(kind_code,alias,search_alias,created_at,updated_at) values('missing','x','x','x','x')")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("kind_aliases foreign key was not enforced")


def test_api_key_is_required():
    with pytest.raises(RuntimeError, match="ANIMAL_API_KEY"):
        require_api_key(SimpleNamespace(animal_api_key=None))


class ResponseSequence:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = 0

    async def get(self, *_args, **_kwargs):
        self.calls += 1
        return httpx.Response(200, json=next(self.payloads), request=httpx.Request("GET", "https://example.test"))


def api_page(total, items):
    return {"response": {"header": {"resultCode": "00"}, "body": {
        "totalCount": total, "items": {"item": items} if items else ""
    }}}


def test_fetch_retries_when_received_count_is_below_total_count():
    item1 = {"kind_cd": "1", "KNm": "하나"}
    item2 = {"kind_cd": "2", "KNm": "둘"}
    item3 = {"kind_cd": "3", "KNm": "셋"}
    client = ResponseSequence([
        api_page(3, [item1, item2]), api_page(3, []),  # truncated first attempt
        api_page(3, [item1, item2]), api_page(3, [item3]),
    ])
    waits = []

    async def fake_sleep(delay):
        waits.append(delay)

    settings = SimpleNamespace(animal_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
                               animal_api_base_url="https://example.test")
    records = asyncio.run(fetch_all(client, settings, "417000", sleep=fake_sleep))
    assert len(records) == 3
    assert client.calls == 4
    assert waits == [0.5]


def test_fetch_throws_after_three_retries():
    client = ResponseSequence([api_page(1, [])] * 4)
    waits = []

    async def fake_sleep(delay):
        waits.append(delay)

    settings = SimpleNamespace(animal_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
                               animal_api_base_url="https://example.test")
    with pytest.raises(RuntimeError, match="totalCount 응답 부족"):
        asyncio.run(fetch_all(client, settings, "417000", sleep=fake_sleep))
    assert client.calls == 4
    assert waits == [0.5, 1.0, 2.0]
