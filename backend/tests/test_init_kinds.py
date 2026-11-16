import sqlite3

from scripts.init_kinds import SQLITE_SCHEMA, SqliteSink, normalize, normalize_record, parse_items


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
    db.executescript(SQLITE_SCHEMA)
    db.execute("insert into kinds(species,kind_code,name,search_name,created_at,updated_at) values('dog','001','믹스견','믹스견','x','x')")
    try:
        db.execute("insert into kind_aliases(kind_code,alias,search_alias,created_at,updated_at) values('missing','x','x','x','x')")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("kind_aliases foreign key was not enforced")
