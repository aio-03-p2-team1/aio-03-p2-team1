"""검색 그래프: 분기·성찰·수정·종료. 구조동물 API 는 FakeAnimal(준비된 응답)로 대체한다."""

import asyncio
from datetime import date, timedelta

from backend.agent.runner import run_search
from backend.storage.sqlite import SqliteStore
from backend.tools.animal_api import SampleAnimalApi
from backend.tools.kakao import KakaoGeocoder

from .conftest import FakeAnimal, FakeEmbedder, api_item, make_settings

OWNER = "owner-a"
START = (date.today() - timedelta(days=7)).isoformat()


async def _nosleep(_):
    return None


def deps(animal=None, **settings):
    return {
        "settings": make_settings(**settings),
        "store": SqliteStore(":memory:"),
        "animal": animal or SampleAnimalApi(),
        "kakao": KakaoGeocoder(None),
        "llm": None,
        "embedder": FakeEmbedder(),
        "sleep": _nosleep,
    }


def search(d, criteria, **extra):
    return asyncio.run(run_search(d, OWNER, {"criteria": criteria, **extra}))


def test_missing_required_asks_then_merges_followup():
    d = deps()
    first = search(d, {"species": "dog"})
    assert first["status"] == "awaiting_input"
    assert {q["field"] for q in first["questions"]} == {"region", "period"}
    assert first["tool_calls"] == []  # API 호출 전에 질문한다
    second = search(d, {"region": "전체", "lost_date": START}, thread_id=first["thread_id"])
    assert second["status"] == "completed"
    assert second["criteria"]["species"] == "dog"  # 같은 세션 조건 병합
    assert second["data_source"] == "sample"


def test_invalid_dates_detected():
    d = deps()
    future = (date.today() + timedelta(days=3)).isoformat()
    run = search(d, {"species": "dog", "region": "전체", "lost_date": future})
    assert run["status"] == "awaiting_input" and run["questions"][0]["field"] == "period"
    rev = search(d, {"species": "dog", "region": "전체", "start_date": START, "end_date": (date.today() - timedelta(days=9)).isoformat()})
    assert rev["questions"][0]["message"].startswith("시작일이")


def test_ranking_evidence_and_unknown_fields():
    animal = FakeAnimal(pages=[[api_item(1), api_item(2, colorCd="흰색", sexCd="M"), api_item(3, colorCd=None, specialMark=None)]])
    run = search(deps(animal), {"species": "dog", "region": "서울특별시", "lost_date": START, "color": "갈색", "sex": "F"})
    assert run["status"] == "completed"
    top = run["candidates"][0]
    assert top["id"].endswith("00001") and "성별 일치" in top["evidence"]["matched"]
    third = next(c for c in run["candidates"] if c["id"].endswith("00003"))
    assert "털색" in third["evidence"]["unknown"]  # 누락은 불일치와 구분
    assert animal.calls[0]["region_code"] == "6110000"


def test_region_abbreviation_fixed_by_reflection():
    animal = FakeAnimal(pages=[[api_item(1)]])
    run = search(deps(animal), {"species": "dog", "region": "서울", "lost_date": START})
    assert run["status"] == "completed"
    assert run["reflections"][0]["issue"] == "arg_mapping"
    assert run["reflections"][0]["strategy"] == "remap_official_code"
    assert animal.calls[0]["region_code"] == "6110000"


def test_region_abbreviation_fails_without_reflection():
    animal = FakeAnimal(pages=[[api_item(1)]])
    run = search(deps(animal), {"species": "dog", "region": "서울", "lost_date": START}, reflection_enabled=False)
    assert run["status"] == "failed" and run["error"]["code"] == "unknown_region"
    assert animal.calls == []


def test_unknown_region_asks_user_instead_of_guessing():
    run = search(deps(FakeAnimal()), {"species": "dog", "region": "아틀란티스", "lost_date": START})
    assert run["status"] == "awaiting_input"
    assert run["reflections"][-1]["strategy"] == "ask_user_region"


def test_duplicates_removed_by_reflection_only_when_enabled():
    pages = [[api_item(i) for i in range(1, 51)], [api_item(50), api_item(51)]]
    with_r = search(deps(FakeAnimal(pages=pages)), {"species": "dog", "region": "전체", "lost_date": START})
    ids = [c["id"] for c in with_r["candidates"]]
    assert len(ids) == len(set(ids))
    assert with_r["reflections"][0]["issue"] == "duplicates"
    without = search(deps(FakeAnimal(pages=pages)), {"species": "dog", "region": "전체", "lost_date": START}, reflection_enabled=False)
    assert without["status"] == "partial" and without["issues"][0]["type"] == "duplicates"


def test_transient_error_retried_and_counted_separately():
    animal = FakeAnimal(pages=[[api_item(1)]], errors=["animal_timeout", None])
    run = search(deps(animal), {"species": "dog", "region": "전체", "lost_date": START})
    assert run["status"] == "completed"
    assert run["retry_count"] == 1 and run["reflection_count"] == 0


def test_auth_error_fails_without_sample_fallback():
    animal = FakeAnimal(pages=[[api_item(1)]], errors=["animal_auth"])
    run = search(deps(animal), {"species": "dog", "region": "전체", "lost_date": START})
    assert run["status"] == "failed" and run["error"]["code"] == "animal_auth"
    assert run["candidates"] == [] and len(animal.calls) == 1  # 인증 오류는 재시도하지 않음


def test_empty_narrow_result_asks_to_widen_not_silently():
    animal = FakeAnimal(pages=[[]])
    run = search(deps(animal), {"species": "dog", "region": "경기도", "lost_date": START})
    assert run["status"] == "awaiting_input"
    assert run["criteria"]["region"] == "경기도"  # 조건을 조용히 완화하지 않는다
    assert "전체" in run["questions"][0]["message"]


def test_empty_all_region_is_completed_with_scope():
    run = search(deps(FakeAnimal(pages=[[]])), {"species": "dog", "region": "전체", "lost_date": START})
    assert run["status"] == "completed" and run["end_reason"] == "empty_result"
    assert run["scope"]["complete"] is True and run["scope"]["total_count"] == 0


def test_partial_scope_when_page_limit_reached():
    pages = [[api_item(i) for i in range(1001)]]
    run = search(deps(FakeAnimal(pages=pages), max_search_pages=1), {"species": "dog", "region": "전체", "lost_date": START})
    assert run["scope"]["complete"] is False and run["partial"] is True
    assert len(run["candidates"]) == 300


def test_memory_fills_only_optional_features():
    d = deps(FakeAnimal(pages=[[api_item(1)]]))
    asyncio.run(d["store"].put(OWNER, "memory", "choco", {"confirmed": {"color": "갈색", "region": "부산광역시"}}))
    run = search(d, {"species": "dog", "region": "전체", "lost_date": START}, profile_id="choco")
    assert run["memory_used"] == {"color": "갈색"}
    assert run["criteria"]["region"] == "all"  # 현재 요청 조건 우선
