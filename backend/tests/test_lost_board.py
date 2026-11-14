"""실종 정보 게시판 + 공공데이터 분실 신고.

- 분실 신고 변환: 개인정보 제거, 연락처 가리기, 날짜·사진 주소 변환, 고정 ID
- 목록 캐시(LostFeed): 축종 3번 호출, 캐시·LRU, 실패 구분
- /posts: 회원 글과 합치기, 필터·페이지, 분실 신고 실패 시 회원 글 유지, 상세 조회
외부 API 는 가짜 객체로 대체한다(실제 호출 없음). 값은 시험용으로 만든 것이다.
"""

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.routers.posts import kst_today
from backend.tools.lost_animal_api import (
    CONTACT_MASK,
    LostAnimalApiError,
    LostPage,
    lost_id,
    mask_contacts,
    normalize_lost,
)
from backend.tools.lost_feed import FRESH_SECONDS, STALE_SECONDS, LostFeed

from .conftest import ORIGIN, build_ctx, signup

PRIVATE = ("callName", "callTel", "rfidCd", "happenAddrDtl")


def raw(n: int, days_ago: int = 1, **over) -> dict:
    """실제 응답과 같은 필드 이름의 시험용 원본 항목."""
    day = kst_today() - timedelta(days=days_ago)
    data = {
        "happenDt": f"{day.isoformat()} 10:00:00.0",
        "happenAddr": f"서울특별시 강동구 시험로 {n}",
        "happenAddrDtl": "101동 202호",
        "happenPlace": "공원 입구",
        "kindCd": "믹스견",
        "colorCd": "흰색",
        "sexCd": "F",
        "age": "3살",
        "specialMark": f"꼬리가 짧아요 {n}",
        "popfile": f"http://openapi.animal.go.kr/openapi/service/rest/fileDownloadSrc.jsp?fileName={n}.jpg",
        "orgNm": "서울특별시 강동구",
        "callName": "홍길동",
        "callTel": "010-0000-0000",
        "rfidCd": "410000000000000",
    }
    data.update(over)
    return data


class FakeLostApi:
    """축종별 원본 항목을 돌려주는 가짜 분실동물 API. 호출 기록을 남긴다."""

    def __init__(self, by_species=None, fail=None):
        self.by_species = by_species or {}
        self.fail = fail
        self.calls = []

    async def search(self, *, start, end, species=None, page=1, rows=100, **_):
        self.calls.append((start, end, species, page))
        if self.fail:
            raise LostAnimalApiError(self.fail)
        items = [i for i in self.by_species.get(species, [])
                 if start.isoformat() <= i["happenDt"][:10] <= end.isoformat()]
        return LostPage(items=items, total_count=len(items), page=page, rows=rows)


def run(coro):
    return asyncio.run(coro)


# ── 변환 ───────────────────────────────────────────────


def test_normalize_drops_private_fields_and_converts():
    item = normalize_lost(raw(1), "dog")
    text = repr(item)
    for value in ("홍길동", "010-0000-0000", "410000000000000", "101동 202호"):
        assert value not in text  # 개인정보 값이 어디에도 남지 않는다
    assert item["source"] == "lost_api" and item["species"] == "dog"
    assert item["lost_date"] == (kst_today() - timedelta(days=1)).isoformat()
    assert item["photo_url"].startswith("https://openapi.animal.go.kr/")
    assert item["region"] == "서울특별시 강동구" and item["lost_place"] == "서울특별시 강동구 시험로 1"
    assert item["breed"] == "믹스견" and item["sex"] == "F" and item["age"] == "3살"


@pytest.mark.parametrize("text", [
    "목줄에 010-1234-5678 적혀 있어요", "연락 01012345678", "집 02-123-4567", "02)1234-5678 로", "+82 10 1234 5678",
])
def test_contacts_in_special_mark_are_masked(text):
    masked = mask_contacts(text)
    assert CONTACT_MASK in masked
    assert not any(ch.isdigit() for ch in masked.replace(CONTACT_MASK, ""))


def test_mask_keeps_ordinary_numbers():
    assert mask_contacts("3살, 몸무게 5kg, 2026년 생") == "3살, 몸무게 5kg, 2026년 생"


def test_id_is_stable_and_starts_with_date():
    a, b = lost_id(raw(1), "dog"), lost_id(raw(1), "dog")
    assert a == b and a.startswith("lost-") and len(a) == len("lost-YYYYMMDD-") + 12
    assert lost_id(raw(2), "dog") != a
    assert normalize_lost(raw(1, happenDt="날짜 아님"), "dog") is None  # 날짜를 못 읽으면 만들지 않는다


# ── 목록 캐시 ──────────────────────────────────────────


def test_feed_calls_each_species_once_and_caches():
    api = FakeLostApi({"dog": [raw(1), raw(2, days_ago=3)], "cat": [raw(3, kindCd="코리안숏헤어")]})
    now = [0.0]
    feed = LostFeed(api, clock=lambda: now[0])
    end = kst_today()
    start = end - timedelta(days=30)

    snap = run(feed.snapshot(start, end))
    assert sorted(c[2] for c in api.calls) == ["cat", "dog", "etc"]  # 축종별 1번씩
    assert [i["lost_date"] for i in snap.items] == sorted([i["lost_date"] for i in snap.items], reverse=True)
    assert {i["species"] for i in snap.items} == {"dog", "cat"}

    now[0] = FRESH_SECONDS - 1
    run(feed.snapshot(start, end))
    assert len(api.calls) == 3  # 10분 안에는 다시 부르지 않는다


def test_feed_returns_stale_immediately_then_refreshes():
    api = FakeLostApi({"dog": [raw(1)]})
    now = [0.0]
    feed = LostFeed(api, clock=lambda: now[0])
    end = kst_today()
    start = end - timedelta(days=7)

    async def scenario():
        await feed.snapshot(start, end)
        now[0] = FRESH_SECONDS + 1  # 오래됐지만 1시간 안
        stale = await feed.snapshot(start, end)
        for _ in range(20):  # 뒤에서 새로 받는 작업이 끝날 기회를 준다
            await asyncio.sleep(0)
        return stale

    stale = run(scenario())
    assert len(stale.items) == 1
    assert len(api.calls) == 6  # 처음 3번 + 뒤에서 새로 받은 3번
    assert STALE_SECONDS > FRESH_SECONDS


def test_feed_failure_is_an_error_not_empty():
    feed = LostFeed(FakeLostApi(fail="lost_auth"))
    with pytest.raises(LostAnimalApiError):
        run(feed.snapshot(kst_today() - timedelta(days=7), kst_today()))


def test_feed_detail_refetches_only_that_day():
    target = raw(5, days_ago=10)
    api = FakeLostApi({"dog": [target]})
    feed = LostFeed(api)
    item_id = lost_id(target, "dog")
    found = run(feed.get(item_id))
    assert found and found["id"] == item_id
    day = kst_today() - timedelta(days=10)
    assert {(c[0], c[1]) for c in api.calls} == {(day, day)}  # 그 날짜 하루만 조회
    assert run(feed.get("lost-19990101-000000000000")) is None


# ── /posts ─────────────────────────────────────────────


def client_with(api):
    ctx = build_ctx()
    ctx.lost = LostFeed(api) if api is not None else None
    return TestClient(create_app(ctx), headers={"Origin": ORIGIN})


def member_body(**over):
    data = {
        "pet_name": "초코", "species": "dog", "region": "서울특별시",
        "lost_date": (kst_today() - timedelta(days=2)).isoformat(), "breed": "푸들",
        "description": "갈색 작은 강아지, 노란 목줄",
    }
    data.update(over)
    return data


def test_list_merges_member_posts_and_lost_reports_by_date():
    api = FakeLostApi({"dog": [raw(1, days_ago=1), raw(2, days_ago=5)], "cat": [raw(3, days_ago=3)]})
    with client_with(api) as client:
        signup(client)
        client.post("/api/v1/posts", json=member_body())
        body = client.get("/api/v1/posts").json()
    assert body["count"] == 4 and body["member_count"] == 1 and body["lost_count"] == 3
    assert body["lost"]["status"] == "ok"
    assert [i["lost_date"] for i in body["items"]] == sorted([i["lost_date"] for i in body["items"]], reverse=True)
    assert {i["source"] for i in body["items"]} == {"member", "lost_api"}
    assert all("description" not in i for i in body["items"])  # 목록에는 긴 설명을 보내지 않는다
    assert "010-0000-0000" not in str(body) and "홍길동" not in str(body)


def test_filters_and_pages_use_one_cached_fetch():
    dogs = [raw(n, days_ago=1 + n % 20) for n in range(45)]
    api = FakeLostApi({"dog": dogs, "cat": [raw(100, kindCd="코리안숏헤어", orgNm="경기도 수원시")]})
    with client_with(api) as client:
        first = client.get("/api/v1/posts?page=1").json()
        second = client.get("/api/v1/posts?page=2").json()
        cats = client.get("/api/v1/posts?species=cat").json()
        gyeonggi = client.get("/api/v1/posts?region=경기도").json()
        week = client.get("/api/v1/posts?days=7").json()
    assert first["pages"] == 3 and len(first["items"]) == 20 and len(second["items"]) == 20
    assert {i["id"] for i in first["items"]}.isdisjoint({i["id"] for i in second["items"]})
    assert cats["count"] == 1 and gyeonggi["count"] == 1
    assert week["count"] < first["count"]
    # 기본 30일 1번 + 7일 1번 = 기간 2개 × 축종 3번. 필터·페이지 변경은 다시 부르지 않는다.
    assert len(api.calls) == 6


def test_lost_failure_keeps_member_posts():
    with client_with(FakeLostApi(fail="lost_rate_limit")) as client:
        signup(client)
        client.post("/api/v1/posts", json=member_body())
        body = client.get("/api/v1/posts").json()
    assert body["count"] == 1 and body["items"][0]["source"] == "member"
    assert body["lost"]["status"] == "unavailable" and body["lost"]["error_code"] == "lost_rate_limit"


def test_without_key_board_is_member_only():
    with client_with(None) as client:
        body = client.get("/api/v1/posts").json()
        assert body["lost"] == {"status": "not_configured"} and body["count"] == 0
        assert client.get("/api/v1/posts/lost/lost-20261101-0123456789ab").status_code == 404
        assert client.get("/api/v1/health").json()["lost_data_source"] == "off"


def test_lost_detail_has_description_without_private_fields():
    target = raw(7, specialMark="겁이 많아요. 목걸이에 010-9999-8888")
    with client_with(FakeLostApi({"dog": [target]})) as client:
        item_id = client.get("/api/v1/posts").json()["items"][0]["id"]
        detail = client.get(f"/api/v1/posts/lost/{item_id}").json()
        assert client.get("/api/v1/posts/lost/not-an-id").status_code == 404
        assert client.get("/api/v1/posts/lost/lost-20261101-0123456789ab").status_code == 404
    assert detail["description"].startswith("겁이 많아요.") and CONTACT_MASK in detail["description"]
    assert "010-9999-8888" not in str(detail) and "callTel" not in detail and "홍길동" not in str(detail)
