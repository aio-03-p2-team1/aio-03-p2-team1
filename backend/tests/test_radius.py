"""검색 반경: 실종 후 날짜별 반경, 반경 밖 제외·임베딩 제외, 0건이면 넓히기 질문, 대체 경로.

카카오는 모의 transport 로 대체한다(실제 호출 없음). 좌표는 시험용 고정값이다.
"""

import asyncio
from datetime import date, timedelta

import httpx
import pytest

from backend.agent import radius as radius_mod
from backend.agent.radius import haversine_km, recommended_step
from backend.agent.runner import run_search
from backend.storage.sqlite import SqliteStore
from backend.tools.kakao import KakaoGeocoder

from .conftest import FakeAnimal, FakeEmbedder, api_item, make_settings

OWNER = "owner-radius"
LOST_PLACE = "서울특별시 강서구 화곡동"
COORDS = {
    LOST_PLACE: (37.541, 126.840),
    "서울특별시 강서구": (37.551, 126.849),  # 약 1.3km
    "서울특별시 양천구": (37.517, 126.866),  # 약 3.5km
    "서울특별시 노원구": (37.654, 127.056),  # 약 23km
}


@pytest.fixture(autouse=True)
def _clear_coord_cache():
    radius_mod._COORD_CACHE.clear()
    yield
    radius_mod._COORD_CACHE.clear()


def kakao(calls=None, fail=()):
    def handler(request: httpx.Request):
        query = request.url.params["query"]
        if calls is not None:
            calls.append(query)
        if query in fail:
            return httpx.Response(500)
        if query not in COORDS:
            return httpx.Response(200, json={"documents": []})
        lat, lng = COORDS[query]
        return httpx.Response(200, json={"documents": [{"x": str(lng), "y": str(lat)}]})

    return KakaoGeocoder("test-key", transport=httpx.MockTransport(handler))


async def _nosleep(_):
    return None


def deps(animal, geocoder=None):
    return {
        "settings": make_settings(),
        "store": SqliteStore(":memory:"),
        "animal": animal,
        "kakao": geocoder if geocoder is not None else kakao(),
        "llm": None,
        "embedder": FakeEmbedder(),
        "sleep": _nosleep,
    }


def items(*orgs):
    return [api_item(i + 1, orgNm=org) for i, org in enumerate(orgs)]


def lost(days):
    return (date.today() - timedelta(days=days)).isoformat()


def search(d, criteria, **extra):
    return asyncio.run(run_search(d, OWNER, {"criteria": criteria, **extra}))


def base(days=2, **more):
    return {"species": "dog", "region": "서울특별시", "lost_date": lost(days), "lost_place": LOST_PLACE, **more}


def test_recommended_step_by_days_since_lost():
    today = date(2026, 11, 14)
    assert recommended_step("2026-11-12", today) == 0  # 2일 → 3km
    assert recommended_step("2026-11-08", today) == 1  # 6일 → 10km
    assert recommended_step("2026-11-01", today) == 2  # 13일 → 20km
    assert recommended_step("2026-10-01", today) == 3  # 그 이후 → 조회 지역 전체
    assert recommended_step(None, today) == 3
    assert 1.0 < haversine_km(COORDS[LOST_PLACE], COORDS["서울특별시 강서구"]) < 2.0


def test_outside_radius_is_excluded_and_not_embedded():
    animal = FakeAnimal(pages=[items("서울특별시 강서구", "서울특별시 양천구", "서울특별시 노원구", "서울특별시 없는구")])
    d = deps(animal)
    run = search(d, base(days=2))
    assert run["status"] == "completed"
    r = run["radius"]
    assert r["applied"] and r["radius_km"] == 3.0 and r["step"] == 0
    assert (r["inside"], r["unknown"], r["excluded"]) == (1, 1, 2)
    ids = {c["id"] for c in run["candidates"]}
    assert ids == {"448000000001", "448000000004"}  # 강서(반경 안) + 좌표 미확인(제외하지 않음)
    near = next(c for c in run["candidates"] if c["id"] == "448000000001")
    assert 1.0 < near["distance_km"] < 2.0 and near["distance_basis"] == "jurisdiction_center"
    unknown = next(c for c in run["candidates"] if c["id"] == "448000000004")
    assert unknown["distance_km"] is None and unknown["distance_basis"] == "unknown"
    # 반경 밖 2건은 임베딩하지 않는다: 검색 조건 1 + 공고 2
    assert len(d["embedder"].calls[0]) == 3
    assert any(c["tool"] == "kakao_geocode_regions" for c in run["tool_calls"])
    assert run["scope"]["radius"]["radius_km"] == 3.0


def test_empty_radius_asks_then_widens_in_same_thread():
    animal = FakeAnimal(pages=[items("서울특별시 양천구", "서울특별시 노원구")])
    d = deps(animal)
    first = search(d, base(days=2))
    assert first["status"] == "awaiting_input"
    question = next(q for q in first["questions"] if q["field"] == "radius")
    assert question["next_step"] == 1 and "10km" in question["message"]
    assert first["reflections"][0]["strategy"] == "ask_user_to_widen_radius"
    # 사용자가 넓히기에 동의하면 같은 세션에서 다음 단계로 다시 찾는다(조용히 넓히지 않는다).
    second = search(d, {"radius_step": 1}, thread_id=first["thread_id"])
    assert second["status"] == "completed"
    assert second["radius"]["radius_km"] == 10.0
    assert [c["id"] for c in second["candidates"]] == ["448000000001"]  # 양천 포함, 노원 제외


def test_empty_radius_without_reflection_does_not_ask():
    animal = FakeAnimal(pages=[items("서울특별시 노원구")])
    run = search(deps(animal), base(days=2), reflection_enabled=False)
    assert run["status"] == "partial" and run["end_reason"] == "unresolved_issues"
    assert run["candidates"] == []


def test_no_kakao_key_keeps_region_search():
    animal = FakeAnimal(pages=[items("서울특별시 강서구", "서울특별시 노원구")])
    run = search(deps(animal, geocoder=KakaoGeocoder(None)), base(days=2))
    assert run["radius"]["applied"] is False and run["radius"]["reason"] == "not_configured"
    assert len(run["candidates"]) == 2


def test_missing_lost_place_and_old_date_skip_radius():
    calls = []
    animal = FakeAnimal(pages=[items("서울특별시 강서구")])
    run = search(deps(animal, kakao(calls)), {"species": "dog", "region": "서울특별시", "lost_date": lost(2)})
    assert run["radius"]["reason"] == "lost_place_missing"
    old = search(deps(animal, kakao(calls)), base(days=30))
    assert old["radius"]["reason"] == "whole_region" and old["radius"]["radius_km"] is None
    assert calls == []  # 반경을 쓰지 않으면 카카오를 부르지 않는다


def test_center_geocode_failure_is_not_cached_and_keeps_results():
    calls = []
    animal = FakeAnimal(pages=[items("서울특별시 강서구")])
    run = search(deps(animal, kakao(calls, fail={LOST_PLACE})), base(days=2))
    assert run["radius"]["applied"] is False and run["radius"]["reason"] == "center_unavailable"
    assert len(run["candidates"]) == 1
    assert LOST_PLACE not in radius_mod._COORD_CACHE


def test_radius_step_is_validated():
    from backend.agent.criteria import normalize

    assert normalize({"radius_step": "2"})[0]["radius_step"] == 2
    assert "radius_step" not in normalize({"radius_step": "9"})[0]
    assert "radius_step" not in normalize({"radius_step": "-1"})[0]
