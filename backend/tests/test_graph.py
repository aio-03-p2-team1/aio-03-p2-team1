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


def test_breed_code_filters_candidates_before_ranking():
    async def resolve_code(species, code):
        assert species == "dog" and code == "poodle-code"
        return {"kind_code": code, "name": "푸들"}

    animal = FakeAnimal(pages=[[api_item(1, kindNm="푸들"), api_item(2, kindNm="말티즈")]])
    d = deps(animal)
    d["breed_normalizer"] = type("Normalizer", (), {"resolve_code": staticmethod(resolve_code)})()
    run = search(d, {"species": "dog", "region": "전체", "lost_date": START, "breed_code": "poodle-code"})
    assert run["status"] == "completed"
    assert run["criteria"]["breed_code"] == "poodle-code"
    assert [candidate["breed"] for candidate in run["candidates"]] == ["푸들"]
    assert animal.calls[0]["kind"] == "poodle-code"
    assert animal.calls[0]["rows"] == 1000


def test_breed_code_rejected_by_api_retries_without_breed_and_filters_results():
    async def resolve_code(species, code):
        return {"kind_code": code, "name": "페르시안"}

    # 첫 호출(품종 코드 포함)은 응답 오류, 품종 없이 다시 부르면 정상 응답
    animal = FakeAnimal(pages=[[api_item(1, kindNm="페르시안"), api_item(2, kindNm="코리안숏헤어")]], errors=["animal_response"])
    d = deps(animal)
    d["breed_normalizer"] = type("Normalizer", (), {"resolve_code": staticmethod(resolve_code)})()
    run = search(d, {"species": "dog", "region": "전체", "lost_date": START, "breed_code": "00214"})
    assert run["status"] == "completed" and not run.get("error")
    assert [c["kind"] for c in animal.calls] == ["00214", None]
    searches = [c for c in run["tool_calls"] if c["tool"] == "animal_search"]
    assert [c["outcome"] for c in searches] == ["animal_response", "ok"]
    assert "품종 조건 없이" in searches[1]["reason"]
    assert [candidate["breed"] for candidate in run["candidates"]] == ["페르시안"]


def test_api_response_error_without_breed_code_still_fails():
    animal = FakeAnimal(pages=[[api_item(1)]], errors=["animal_response"])
    run = search(deps(animal), {"species": "dog", "region": "전체", "lost_date": START})
    assert run["status"] == "failed" and run["error"]["code"] == "animal_response"
    assert len(animal.calls) == 1


class FakeReviewer:
    """검색 전 입력 검토(review_input)를 흉내 낸다. 판단(바로 찾기/먼저 묻기)을 차례로 돌려준다."""

    model = "fake-review"

    def __init__(self, *actions, error=None, breed_mention="", animal_kind="", info_fields=None):
        self.actions = list(actions) or ["search"]
        self.error = error
        self.breed_mention = breed_mention
        self.animal_kind = animal_kind
        self.info_fields = info_fields or []
        self.calls = []
        self.memories = []

    async def review_input(self, description, photo=None, species="", previous=None, chosen=None):
        from backend.agent.llm import LlmError
        from backend.schemas.llm import InputReviewResult

        self.calls.append((description, photo))
        self.memories.append(previous)
        self.chosen = chosen
        if self.error:
            raise LlmError(self.error)
        action = self.actions.pop(0) if len(self.actions) > 1 else self.actions[0]
        return InputReviewResult(
            organized_text="[털색]: 흰색\n[특징]: 빨간 목줄",
            features={"colors": ["흰색"], "sex": "", "marks": ["빨간 목줄"]},
            duplicates=["흰색(글과 사진)"],
            conflicts=[{"item": "털색", "text_value": "흰색", "photo_value": "갈색"}] if action == "ask" else [],
            action=action,
            question="글에는 흰색, 사진에는 갈색으로 보여요. 어느 쪽이 맞나요?" if action == "ask" else "",
            message="흰색이 글과 사진에 겹쳐 하나로 합쳤어요.",
            breed_mention=self.breed_mention,
            animal_kind=self.animal_kind,
            info_fields=self.info_fields if action == "ask" else [],
            prompt_version="input-review-v2",
        )


PHOTO = {"suitable": True, "species": "dog", "breed": "", "colors": ["흰색"], "sex": "", "marks": []}


def test_input_review_runs_before_search_and_its_features_are_used():
    reviewer = FakeReviewer("search")
    animal = FakeAnimal(pages=[[api_item(1)]])
    d = deps(animal)
    d["llm"] = reviewer
    run = search(d, {"species": "dog", "region": "전체", "lost_date": START,
                     "description": "사진에서 확인한 특징: 흰색\n흰색 강아지, 빨간 목줄"}, photo=PHOTO)
    assert run["status"] == "completed"
    assert reviewer.calls == [("사진에서 확인한 특징: 흰색\n흰색 강아지, 빨간 목줄", PHOTO)]
    review = run["input_review"]
    assert review["action"] == "search" and review["message"] and review["duplicates"] == ["흰색(글과 사진)"]
    assert review["organized_text"].startswith("[털색]: 흰색") and review["photo_used"] is True
    assert run["llm_features"]["colors"] == ["흰색"] and run["llm_features"]["marks"] == ["빨간 목줄"]
    reviews = [c for c in run["tool_calls"] if c["tool"] == "input_review"]
    assert reviews and reviews[0]["outcome"] == "ok" and reviews[0]["action"] == "search"
    assert len(animal.calls) == 1


def test_input_review_asks_before_search_once_per_thread():
    reviewer = FakeReviewer("ask", "ask")
    animal = FakeAnimal(pages=[[api_item(1)]])
    d = deps(animal)
    d["llm"] = reviewer
    criteria = {"species": "dog", "region": "전체", "lost_date": START, "description": "흰색 강아지"}
    first = search(d, criteria, photo=PHOTO)
    assert first["status"] == "awaiting_input"
    assert first["questions"] == [{"field": "input_review", "message": "글에는 흰색, 사진에는 갈색으로 보여요. 어느 쪽이 맞나요?"}]
    assert first["input_review"]["action"] == "ask" and first["input_review"]["conflicts"]
    assert animal.calls == []  # 묻는 동안 공고를 조회하지 않는다
    second = search(d, criteria, photo=PHOTO, thread_id=first["thread_id"])
    assert second["status"] == "completed"  # 같은 대화에서는 다시 묻지 않고 글 기준으로 찾는다
    assert second["input_review"]["action"] == "search" and second["input_review"]["question"] == ""
    assert len(animal.calls) == 1


def test_input_review_without_features_offers_server_options_before_search():
    """특징이 하나도 없어 물을 때는 지역 넓히기 전에, 검색 전에 서버가 정한 보기(털색·성별·특징)를 함께 보낸다."""
    reviewer = FakeReviewer("ask", "ask", info_fields=["color", "sex", "marks"])
    animal = FakeAnimal(pages=[[api_item(1)]])
    d = deps(animal)
    d["llm"] = reviewer
    criteria = {"species": "cat", "region": "전체", "lost_date": START, "description": "으흠"}
    first = search(d, criteria)
    assert first["status"] == "awaiting_input" and animal.calls == []
    fields = {f["field"]: f for f in first["input_review"]["info_request"]}
    assert set(fields) == {"color", "sex", "marks"} and "흰색" in fields["color"]["options"]
    second = search(d, {**criteria, "color": "흰색", "sex": "M"}, thread_id=first["thread_id"])
    assert second["status"] == "completed" and "info_request" not in second["input_review"]
    assert reviewer.chosen == {"color": "흰색", "sex": "M"}  # 고른 털색·성별을 입력 검토에 넘겨 멘트에 함께 말하게 한다


def test_widen_follow_up_without_description_reuses_the_thread_text():
    """넓히기 버튼은 바뀐 조건만 보낸다. 같은 대화의 글로 다시 검토하고 오류 없이 이어 찾는다(기존 다듬기 422 회귀)."""
    reviewer = FakeReviewer("search")
    animal = FakeAnimal(pages=[[api_item(1)]])
    d = deps(animal)
    d["llm"] = reviewer
    first = search(d, {"species": "dog", "region": "경기도", "lost_date": START, "description": "흰색 강아지, 빨간 목줄"})
    second = search(d, {"region": "전체", "radius_step": 3}, thread_id=first["thread_id"])
    assert second["status"] == "completed" and not second.get("error")
    assert second["criteria"]["description"] == "흰색 강아지, 빨간 목줄"
    assert reviewer.calls[-1][0] == "흰색 강아지, 빨간 목줄"


def test_breed_written_in_text_filters_strictly_even_to_zero():
    """글에만 '푸들'을 적어도 푸들 계열만 남긴다. 리트리버·품종 미상·푸들이 아닌 믹스는 뺀다."""
    reviewer = FakeReviewer("search", breed_mention="푸들")
    animal = FakeAnimal(pages=[[
        api_item(1, kindNm="토이 푸들"), api_item(2, kindNm="골든 리트리버"), api_item(3, kindNm="기타"),
        api_item(4, kindNm="믹스견", specialMark="푸들 믹스로 보임"), api_item(5, kindNm="믹스견", specialMark="갈색 단모"),
    ]])
    d = deps(animal)
    d["llm"] = reviewer
    run = search(d, {"species": "dog", "region": "전체", "lost_date": START, "description": "푸들, 갈색 곱슬털"})
    assert run["status"] == "completed"
    assert sorted(c["breed"] for c in run["candidates"]) == ["믹스견", "토이 푸들"]
    assert run["criteria"]["breed"] == "푸들" and not run["criteria"].get("breed_code")
    assert animal.calls[0]["kind"] is None  # 글에서 찾은 품종은 API 품종 코드로 좁히지 않고 계열로 거른다
    assert "푸들 계열만" in run["input_review"]["filters"][0]

    only_retriever = FakeAnimal(pages=[[api_item(1, kindNm="골든 리트리버")]])
    d2 = deps(only_retriever)
    d2["llm"] = FakeReviewer("search", breed_mention="푸들")
    empty = search(d2, {"species": "dog", "region": "전체", "lost_date": START, "description": "푸들"})
    assert empty["candidates"] == []  # 엉뚱한 품종을 보여 주느니 0건


class FakeKindClassifier:
    model = "fake-vision"

    def __init__(self, kinds):
        self.kinds = list(kinds)
        self.batches = []

    async def classify_animal_photos(self, images):
        self.batches.append(len(images))
        return [self.kinds.pop(0) for _ in images]


def test_etc_animal_kind_is_checked_by_text_then_photo(monkeypatch):
    from io import BytesIO
    from PIL import Image
    from backend.tools import remote_photo

    buffer = BytesIO()
    Image.new("RGB", (40, 40), (200, 200, 200)).save(buffer, format="PNG")

    async def fake_fetch(url, **_):
        return buffer.getvalue()

    monkeypatch.setattr(remote_photo, "fetch_photo", fake_fetch)
    etc = {"upKindCd": "429900", "upKindNm": "기타", "kindNm": "기타축종"}
    animal = FakeAnimal(pages=[[
        api_item(1, specialMark="사랑앵무 초록색", **etc),           # 글로 새
        api_item(2, specialMark="송아지 생후 2개월", **etc),          # 글로 소 → 제외
        api_item(3, specialMark="없음", **etc),                    # 사진으로 새
        api_item(4, specialMark="귀여운 아이", **etc),               # 사진으로 토끼 → 제외
        api_item(5, specialMark="없음", popfile1="", popfile2="", **etc),  # 사진 없음 → 모름 → 제외
    ]])
    classifier = FakeKindClassifier(["새", "토끼"])
    d = deps(animal)
    d["llm"] = FakeReviewer("search", animal_kind="새")
    d["photo_llm"] = classifier
    run = search(d, {"species": "etc", "region": "전체", "lost_date": START, "description": "초록색 앵무새"})
    assert run["status"] == "completed"
    assert sorted(c["id"] for c in run["candidates"]) == ["448000000001", "448000000003"]
    assert classifier.batches == [2]  # 글로 모르는 공고만 사진으로, 한 번에
    assert run["kind_check"] == {"target": "새", "checked": 5, "kept": 2, "kept_by_text": 1, "kept_by_photo": 1,
                                 "other_kind": 2, "unknown": 1}
    assert [c["outcome"] for c in run["tool_calls"] if c["tool"] == "animal_kind_photo"] == ["ok"]


def test_input_review_does_not_ask_on_follow_up_after_first_search_went_ahead():
    """첫 검색에서 묻지 않고 찾았으면, 지역 넓히기처럼 같은 대화로 이어 찾을 때 모순 질문을 새로 하지 않는다."""
    reviewer = FakeReviewer("search", "ask")
    animal = FakeAnimal(pages=[[api_item(1)]])
    d = deps(animal)
    d["llm"] = reviewer
    first = search(d, {"species": "dog", "region": "경기도", "lost_date": START, "description": "흰색 강아지"}, photo=PHOTO)
    assert first["input_review"]["action"] == "search"
    second = search(d, {"region": "전체"}, photo=PHOTO, thread_id=first["thread_id"])
    assert len(reviewer.calls) == 2  # 이어 찾을 때도 검토는 하되
    assert second["status"] == "completed" and second["input_review"]["action"] == "search"  # 묻지 않는다
    assert not any(q.get("field") == "input_review" for q in second.get("questions") or [])


def test_thread_keeps_review_memory_and_marks_answered_conflicts_confirmed():
    """서버가 대화 기록에 직전 검토를 남겨 다음 검토에 넘긴다(모델은 스스로 기억하지 못함)."""
    reviewer = FakeReviewer("ask", "search")
    d = deps(FakeAnimal(pages=[[api_item(1)]]))
    d["llm"] = reviewer
    criteria = {"species": "dog", "region": "전체", "lost_date": START, "description": "흰색 강아지"}
    first = search(d, criteria, photo=PHOTO)
    assert reviewer.memories == [None]  # 새 대화는 기억 없이 검토
    assert first["status"] == "awaiting_input"
    search(d, {"description": "[털색]: 흰색\n[특징]: 빨간 목줄"}, photo=PHOTO, thread_id=first["thread_id"])
    memory = reviewer.memories[-1]
    assert memory["organized_text"] == "[털색]: 흰색\n[특징]: 빨간 목줄"
    assert memory["duplicates"] == ["흰색(글과 사진)"]
    assert memory["confirmed_items"] == ["털색"]  # 물었던 항목에 사용자가 답했으므로 확정


def test_input_review_failure_is_reported_not_hidden():
    d = deps(FakeAnimal(pages=[[api_item(1)]]))
    d["llm"] = FakeReviewer(error="llm_timeout")
    run = search(d, {"species": "dog", "region": "전체", "lost_date": START, "description": "흰색 강아지"})
    assert run["status"] == "failed" and run["error"]["code"] == "llm_timeout"
    assert [c["outcome"] for c in run["tool_calls"] if c["tool"] == "input_review"] == ["llm_timeout"]


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
