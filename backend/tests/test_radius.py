"""검색 반경: 실종 후 날짜별 반경, 반경 밖 제외·임베딩 제외, 0건이면 20km 까지 자동 확대 후 넓히기 질문, 대체 경로.

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
from backend.tools.animal_api import Region
from backend.timeutil import kst_today
from backend.tools.kakao import KakaoGeocoder

from .conftest import FakeAnimal, FakeEmbedder, api_item, make_settings, signup

OWNER = "owner-radius"
LOST_PLACE = "서울특별시 강서구 화곡동"
COORDS = {
    LOST_PLACE: (37.541, 126.840),
    "서울특별시 강서구": (37.551, 126.849),  # 약 1.3km
    "서울특별시 양천구": (37.517, 126.866),  # 약 3.5km
    "서울특별시 노원구": (37.654, 127.056),  # 약 23km
    # 넓은 시: 시청 좌표와 읍 좌표가 약 18km 떨어진 실제 사례(경주시 외동읍, 2026-11-16 로컬 확인)
    "경상북도 경주시": (35.856, 129.225),
    "경상북도 경주시 외동읍": (35.717, 129.328),
}


AMBIGUOUS = {LOST_PLACE}


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
        docs = [{"x": str(lng), "y": str(lat)}]
        if query in AMBIGUOUS:  # 동 이름: 법정동 + 행정동(1동, 2동)이 함께 나오는 실제 응답 형태
            docs += [{"x": str(lng + 0.01), "y": str(lat + 0.01)}, {"x": str(lng - 0.01), "y": str(lat - 0.01)}]
        return httpx.Response(200, json={"documents": docs})

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
    return (kst_today() - timedelta(days=days)).isoformat()


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


def test_empty_radius_widens_automatically_3_to_10km():
    animal = FakeAnimal(pages=[items("서울특별시 양천구", "서울특별시 노원구")])
    calls = []
    d = deps(animal, kakao(calls))
    run = search(d, base(days=2))
    # 3km 안에는 없어서 묻지 않고 10km 로 넓혀 찾는다(양천 약 3.5km 포함, 노원 약 23km 제외).
    assert run["status"] == "completed"
    r = run["radius"]
    assert r["requested_km"] == 3.0 and r["radius_km"] == 10.0 and r["step"] == 1
    assert r["auto_widened"] is True and r["widen_trail"] == [3.0, 10.0]
    assert (r["inside"], r["unknown"], r["excluded"]) == (1, 0, 1)
    assert r["next_widen_day"] is None and r["next_radius_km"] == 20.0
    assert [c["id"] for c in run["candidates"]] == ["448000000001"]
    assert run["reflections"] == []  # 판단 수정(질문) 없이 자동 확대
    # 넓힐 때 좌표를 다시 묻지 않는다: 실종 위치 + 관할 2곳 = 3번(그 뒤 보호센터 위치 조회는 별도)
    radius_call = next(c for c in run["tool_calls"] if c["tool"] == "kakao_geocode_regions")
    assert radius_call["args"]["requests"] == 3
    assert calls[:3].count(LOST_PLACE) == 1 and len(set(calls[:3])) == 3


def test_auto_widen_stops_at_20km_then_asks_for_whole_region():
    animal = FakeAnimal(pages=[items("서울특별시 노원구")])
    d = deps(animal)
    first = search(d, base(days=2))
    r = first["radius"]
    assert r["widen_trail"] == [3.0, 10.0, 20.0] and r["radius_km"] == 20.0 and r["step"] == 2
    # 20km 에서도 없으면 조회 지역 전체로는 자동으로 넓히지 않고 묻는다.
    assert first["status"] == "awaiting_input"
    question = next(q for q in first["questions"] if q["field"] == "radius")
    assert question["next_step"] == 3 and "20km" in question["message"] and "조회 지역 전체" in question["message"]
    assert first["reflections"][0]["strategy"] == "ask_user_to_widen_radius"
    second = search(d, {"radius_step": 3}, thread_id=first["thread_id"])
    assert second["status"] == "completed"
    assert second["radius"]["applied"] is False and second["radius"]["reason"] == "whole_region"
    assert [c["id"] for c in second["candidates"]] == ["448000000001"]


def test_no_widening_when_results_exist():
    animal = FakeAnimal(pages=[items("서울특별시 강서구", "서울특별시 양천구")])
    r = search(deps(animal), base(days=2))["radius"]
    assert r["radius_km"] == 3.0 and r["auto_widened"] is False and r["widen_trail"] == [3.0]


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
    # 반경을 쓰지 않으면 실종 위치·관할 좌표를 조회하지 않는다.
    # (locate 노드가 상위 후보 보호센터 주소를 조회하는 호출은 반경과 무관하므로 허용)
    assert not any(q == LOST_PLACE or q in COORDS for q in calls)
    for r in (run, old):
        assert not any(c["tool"] == "kakao_geocode_regions" for c in r["tool_calls"])


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


def test_dong_name_with_multiple_documents_still_sets_center():
    # 실제 카카오: "서울특별시 마포구 망원동" → 망원동·망원1동·망원2동 3건. 첫 문서를 중심으로 쓴다.
    animal = FakeAnimal(pages=[items("서울특별시 강서구", "서울특별시 노원구")])
    run = search(deps(animal, kakao()), base(days=2))
    assert run["radius"]["applied"] is True
    assert run["radius"]["center"] == {"lat": COORDS[LOST_PLACE][0], "lng": COORDS[LOST_PLACE][1]}


def test_geocode_default_still_rejects_ambiguous_address():
    # 보호센터 마커용 기본 조회는 여러 건이면 여전히 좌표를 쓰지 않는다.
    result = asyncio.run(kakao().geocode(LOST_PLACE))
    assert result == {"status": "unavailable", "reason": "address_ambiguous"}
    first = asyncio.run(kakao().geocode(LOST_PLACE, allow_ambiguous=True))
    assert first["status"] == "ok" and first["ambiguous"] == 3


# ── 지도에서 찍은 좌표를 반경 중심으로 ─────────────────────────────

PIN = (37.552, 126.851)  # 강서구 중심(시험값)에서 약 0.2km


def test_user_pin_is_center_without_geocoding_lost_place():
    calls = []
    animal = FakeAnimal(pages=[items("서울특별시 강서구", "서울특별시 노원구")])
    run = search(deps(animal, kakao(calls)), base(days=2, lost_lat=PIN[0], lost_lng=PIN[1]))
    assert run["radius"]["applied"] is True and run["radius"]["center_source"] == "user_pin"
    assert run["radius"]["center"] == {"lat": PIN[0], "lng": PIN[1]}
    assert LOST_PLACE not in calls  # 실종 위치 주소는 다시 좌표화하지 않는다
    assert run["radius"]["inside"] == 1 and run["radius"]["excluded"] == 1


@pytest.mark.parametrize("lat, lng", [(10.0, 126.8), (37.5, 200.0), ("abc", 126.8)])
def test_bad_pin_falls_back_to_address(lat, lng):
    from backend.agent import criteria as crit

    criteria, _, errors = crit.normalize({**base(days=2), "lost_lat": lat, "lost_lng": lng})
    assert errors == [] and "lost_lat" not in criteria  # 범위 밖·숫자 아님 → 좌표 버리고 주소로
    animal = FakeAnimal(pages=[items("서울특별시 강서구")])
    calls = []
    run = asyncio.run(run_search(deps(animal, kakao(calls)), OWNER, {"criteria": {**base(days=2)}}))
    assert run["radius"]["center_source"] == "address" and LOST_PLACE in calls


def test_new_lost_place_does_not_reuse_previous_pin():
    from backend.agent import criteria as crit

    session = {"lost_place": "서울특별시 마포구 망원동", "lost_lat": "37.55", "lost_lng": "126.90"}
    merged, _ = crit.merge_conditions({"lost_place": LOST_PLACE}, session, None)
    assert "lost_lat" not in merged and merged["lost_place"] == LOST_PLACE
    merged, _ = crit.merge_conditions({"radius_step": "1"}, session, None)  # 넓히기만 보내면 이전 좌표 유지
    assert merged["lost_lat"] == "37.55"


def test_api_rejects_pin_outside_korea(client):
    signup(client)
    body = {"criteria": {**base(days=2), "lost_lat": 51.5, "lost_lng": -0.12}}
    assert client.post("/api/v1/searches", json=body).status_code == 422


def test_summary_has_days_and_next_widen_day_for_guide_text():
    animal = FakeAnimal(pages=[items("서울특별시 강서구")])
    run = search(deps(animal), base(days=2, lost_lat=PIN[0], lost_lng=PIN[1]))
    r = run["radius"]
    assert r["days_since_lost"] == 2 and r["auto"] is True and r["next_widen_day"] == 4  # 4일째부터 10km
    widened = search(deps(FakeAnimal(pages=[items("서울특별시 강서구")])), base(days=2, radius_step=1))
    assert widened["radius"]["auto"] is False and widened["radius"]["next_widen_day"] is None



# ── 구조 장소(읍면동) 기준 거리 ─────────────────────────────────

@pytest.mark.parametrize("place, token", [
    ("외동읍 석계평리길 부근", "외동읍"),
    ("경주시 외동읍 입실리", "외동읍"),
    ("이촌동 이촌아파트 도로변 상가", "이촌동"),
    ("고덕래미안힐스테이트 306동 놀이터 앞", None),  # 아파트 동 번호는 읍면동이 아님
    ("홍은동주민센터옆 주차장", None),  # 붙여 쓴 말은 뽑지 않음(관할 기준으로 대신)
    ("서울 구로구 고척로21다길 13 인근", None),
    ("차량으로 이동 중 발견", None),  # 두 글자 일반 낱말은 읍면동으로 보지 않음
    (None, None),
])
def test_area_token(place, token):
    assert radius_mod.area_token(place) == token


def test_rescue_area_is_used_before_jurisdiction_center():
    # 실종: 경주시 외동읍. 같은 읍에서 구조됐지만 관할(경주시청)까지는 약 18km 인 공고가 반경 안에 들어와야 한다.
    pin = (35.7174, 129.3276)
    same_town = api_item(1, orgNm="경상북도 경주시", happenPlace="외동읍 석계평리길 부근")
    no_town = api_item(2, orgNm="경상북도 경주시", happenPlace="시내 공원")
    # 가짜 API 지역 목록 기본값은 서울·경기뿐이라 경상북도를 넣어 준다(없으면 지역 매핑 실패로 질문 상태가 됨).
    animal = FakeAnimal(pages=[[same_town, no_town]], regions=[Region("6470000", "경상북도")])
    criteria = {"species": "dog", "region": "경상북도", "lost_date": lost(2), "lost_place": "경상북도 경주시 외동읍",
                "lost_lat": pin[0], "lost_lng": pin[1]}
    run = search(deps(animal), criteria)
    r = run["radius"]
    assert r["applied"] is True and r["inside"] == 1 and r["excluded"] == 1 and r["by_rescue_area"] == 1
    near = run["candidates"][0]
    assert near["distance_basis"] == "rescue_area" and near["distance_km"] < 1.0
