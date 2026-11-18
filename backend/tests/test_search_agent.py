"""검색 에이전트 루프: 읽기 → 판단 → 조건 수정 → 다시 찾기 → 종료. LLM은 가짜 client(실제 호출 아님)."""

import asyncio
import json

import fakeredis
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.agent import search_agent as SA
from backend.agent.ranking import confidence_signals
from backend.agent.runner import run_search
from backend.agent.search_cache import SearchCache

from .conftest import FakeAnimal, api_item
from .test_graph import START, deps, search

MIXED = {"species": "dog", "region": "전체", "lost_date": START, "description": "믹스견 흰색 엉덩이 얼룩"}
SUFFICIENT = {"species": "dog", "region": "전체", "lost_date": START,
              "color": "갈색", "sex": "F", "description": "곱슬털"}


class FakeAgentClient:
    """bind_tools → ainvoke 흉내. 정해 둔 순서대로 도구를 고르고, 다 쓰면 Finish 를 고른다."""

    def __init__(self, script=(), error=None):
        self.script, self.error = list(script), error
        self.calls, self.bound = [], None

    def bind_tools(self, tools, **options):
        self.bound = ([t.__name__ for t in tools], options)
        return self

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        if self.error:
            raise self.error
        name, args = self.script.pop(0) if self.script else ("Finish", {"note": "충분함"})
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{len(self.calls)}"}])


def agent_deps(script=(), **kw):
    client = FakeAgentClient(script, **kw)
    return {**deps(), "search_agent": SA.SearchAgent(client, "fake-model")}, client


def tools_used(run):
    return [entry["tool"] for entry in run["agent_decision"]["log"] if "tool" in entry]


def test_confidence_low_for_mixed_breed_without_photo():
    cands = [{"semantic_score": 0.8, "evidence": {"matched": ["털색"]}}, {"semantic_score": 0.6}]
    assert "mixed_breed" in confidence_signals(cands, {"description": "믹스견 하얀색 엉덩이에 얼룩"})["reasons"]
    # 사진을 받았는지는 설명 글 문장이 아니라 서버가 보관한 사진 분석 결과로만 판단한다.
    text_only = confidence_signals(cands, {"description": "사진에서 확인한 특징: 믹스견, 흰색\n엉덩이 얼룩"})
    assert "mixed_breed" in text_only["reasons"]  # 문장만으로는 사진을 받은 것으로 보지 않음
    good = {"suitable": True, "colors": ["흰색"], "marks": ["얼룩"], "sex": "", "breed": "", "species": "dog"}
    assert "mixed_breed" not in confidence_signals(cands, {"description": "믹스견"}, None, good)["reasons"]
    bad = {**good, "suitable": False}
    assert "mixed_breed" in confidence_signals(cands, {"description": "믹스견"}, None, bad)["reasons"]  # 쓸 수 없는 사진


def test_feature_updates_need_evidence_in_user_text():
    source = "믹스견 하얀색 엉덩이에 얼룩 수컷"
    accepted, rejected = SA.validate_features(
        {"colors": ["흰색", "검정"], "breed": "말티즈", "sex": "F", "marks": ["얼룩", "꼬리 짧음"]}, source)
    assert accepted == {"colors": ["흰색"], "marks": ["얼룩"]}
    assert len(rejected) == 3  # 품종은 처리하지 않고 검정·암컷·꼬리 짧음은 거부
    accepted, _ = SA.validate_features({"breed": "믹스견", "sex": "M"}, source)
    assert accepted == {"sex": "M"}


def test_read_results_hides_contacts_ids_and_dates():
    state = {"candidates": [{"id": "4411", "notice_no": "경기-1", "rank": 1, "breed": "믹스견", "color": "흰색",
                             "happen_date": "2026-11-10", "care": {"tel": "010-0000-0000"}, "semantic_score": 0.71234,
                             "evidence": {"matched": ["털색: 흰색"]}}]}
    row = SA.read_results(state, 5)[0]
    assert len(SA.TOOLS) == 6  # 읽기는 메시지로 주고 도구로 부르지 않음
    assert set(row) == {"순위", "품종", "털색", "성별", "나이", "특징", "유사도", "일치", "불일치", "미확인"}
    assert row["유사도"] == 0.712


def test_agent_reads_updates_reruns_and_finishes():
    d, client = agent_deps([
        ("UpdateFeatures", {"colors": ["흰색"], "marks": ["얼룩"], "reason": "설명의 털색과 특징을 조건에 넣어요."}),
        ("Finish", {"note": "다시 정렬한 결과가 설명과 맞음"}),
    ])
    run = search(d, MIXED)
    assert run["status"] == "completed" and run["candidates"]
    assert tools_used(run) == ["update_features", "finish"]
    first = client.calls[0][1].content
    assert "사용자 원문" in first and "상위 후보" in first  # 읽을거리는 처음 메시지에 미리 들어 있음
    decision = run["agent_decision"]
    assert decision["source"] == "llm" and decision["final_tool"] == "finish" and decision["reruns"] == 1
    assert run["criteria"]["color"] == "흰색"
    base = search(deps(), MIXED)["trace"].count("rank")
    assert run["trace"].count("rank") == base + 1  # 수정 후 한 번 더 정렬
    assert any(e["step"] == "rerun_result" for e in decision["log"])
    # LLM은 도구 결과(ToolMessage)와 다시 찾은 결과(HumanMessage)를 이어서 받는다.
    last = client.calls[-1]
    assert isinstance(last[-1], HumanMessage) and "다시 찾은 결과" in last[-1].content
    assert any(isinstance(m, ToolMessage) for m in last)
    assert client.bound[1] == {"tool_choice": "required", "parallel_tool_calls": False}


def test_fabricated_feature_rejected_without_rerun():
    d, _ = agent_deps([("UpdateFeatures", {"marks": ["꼬리 짧음"], "reason": "특징을 바꿔요."})])
    run = search(d, MIXED)
    log = run["agent_decision"]["log"]
    update = next(e for e in log if e.get("tool") == "update_features")
    assert update["ok"] is False and "원문에 없는 말" in update["rejected"][0]
    assert run["agent_decision"]["reruns"] == 0
    assert run["trace"].count("rank") == search(deps(), MIXED)["trace"].count("rank")  # 다시 찾지 않음


def test_rerun_limit_and_step_limit():
    upd = ("UpdateFeatures", {"colors": ["흰색"], "reason": "털색을 넣어요."})
    run = search(agent_deps([upd, upd, upd])[0], MIXED)
    assert run["agent_decision"]["reruns"] == SA.MAX_RERUNS
    assert run["agent_decision"]["log"][-2]["ok"] is False  # 세 번째 수정은 한도로 거부
    run = search(agent_deps([("RelaxCondition", {"field": "breed", "reason": "풀어요."})] * 10)[0], MIXED)
    assert run["agent_decision"]["source"] == "step_limit" and run["agent_request"] is None
    assert run["candidates"]  # 한도에 걸려도 결과는 보여 준다


def test_widen_radius_rejected_when_radius_not_applied():
    run = search(agent_deps([("WidenRadius", {"reason": "넓혀요."})])[0], MIXED)
    widen = next(e for e in run["agent_decision"]["log"] if e.get("tool") == "widen_radius")
    assert widen["ok"] is False and run["agent_decision"]["reruns"] == 0


def test_photo_request_once_per_thread_and_server_reason():
    d, _ = agent_deps([("RequestPhoto", {"reason": "공고 4411000 과 비슷해요"})])
    first = search(d, MIXED)
    assert first["agent_request"] == {"type": "photo", "reason": SA.rules.DEFAULT_REASON["photo"]}  # 숫자 문장 교체
    d["search_agent"]._client.script = [("RequestPhoto", {"reason": "사진을 올려 주세요."})]
    again = search(d, {"description": "믹스견 흰색 꼬리"}, thread_id=first["thread_id"])
    assert again["agent_request"] is None  # 같은 대화에서 사진은 한 번만
    photo = next(e for e in again["agent_decision"]["log"] if e.get("tool") == "request_photo")
    assert photo["ok"] is False


def test_declined_field_not_requested():
    d, _ = agent_deps([("RequestInfo", {"field": "size", "reason": "크기를 알려 주세요."})])
    run = search(d, MIXED, declined=["size"])
    assert run["agent_request"] is None and run["agent_decision"]["final_tool"] == "finish"


def test_no_llm_or_llm_error_keeps_results():
    run = search(deps(), MIXED)
    assert run["agent_decision"]["source"] == "no_llm" and run["candidates"]
    run = search(agent_deps(error=TimeoutError())[0], MIXED)
    assert run["agent_decision"]["source"] == "llm_error" and run["candidates"]


def test_update_features_schema_and_runtime_exclude_breed():
    assert 'breed' not in SA.UpdateFeatures.model_fields
    assert '품종·성별·특징' not in SA.SYSTEM_PROMPT
    accepted, _ = SA.validate_features({'breed': '믹스견'}, '믹스견 흰색')
    assert accepted == {}
    d, _ = agent_deps([('UpdateFeatures', {'breed': '믹스견', 'reason': '품종 변경'})])
    run = search(d, MIXED)
    assert not run['criteria'].get('breed')
    assert run['agent_decision']['reruns'] == 0


def test_relaxing_breed_clears_code_together():
    state = {'criteria': {'species': 'dog', 'breed': '푸들', 'breed_code': '1'}}
    result = SA.execute_tool('relax_condition', {'field': 'breed'}, state, {})
    assert 'breed' not in result['update']['criteria']
    assert 'breed_code' not in result['update']['criteria']


def test_stored_photo_features_stop_photo_request_and_feed_ranking():
    photo = {"suitable": True, "species": "dog", "breed": "", "breed_code": "", "colors": ["흰색"], "sex": "M",
             "marks": ["빨간 목줄"], "reason_code": None}
    d, _ = agent_deps([("RequestPhoto", {"reason": "사진을 올려 주세요."})])
    run = search(d, {**MIXED, "description": "믹스견"}, photo=photo)
    assert run["photo_features"] == photo
    assert run["agent_request"] is None  # 사진을 이미 받아 사진 요청은 거부됨
    assert run["agent_decision"]["log"] and any(e.get("tool") == "request_photo" and e["ok"] is False
                                                 for e in run["agent_decision"]["log"])
    assert set(run["llm_features"]["colors"]) == {"흰색"} and run["llm_features"]["sex"] == "M"


def test_high_confidence_result_is_reviewed_once():
    d, client = agent_deps()
    d["animal"] = FakeAnimal(pages=[[api_item(1)]])
    run = search(d, SUFFICIENT)
    assert run["confidence"]["low"] is False
    assert run["status"] == "completed" and len(client.calls) == 1
    assert tools_used(run) == ["finish"] and run["agent_request"] is None
    assert run["agent_decision"]["reruns"] == 0


@pytest.mark.parametrize("tool,args", [
    ("RequestPhoto", {"reason": "사진을 올려 주세요."}),
    ("RequestInfo", {"field": "size", "reason": "크기를 알려 주세요."}),
])
def test_high_confidence_review_rejects_unnecessary_questions(tool, args):
    d, _ = agent_deps([(tool, args)])
    d["animal"] = FakeAnimal(pages=[[api_item(1)]])
    run = search(d, SUFFICIENT)
    assert run["confidence"]["low"] is False and run["agent_request"] is None
    assert run["agent_decision"]["log"][1]["ok"] is False
    assert tools_used(run)[-1] == "finish"


@pytest.mark.parametrize("region", ["경기도", "전체"])
def test_empty_api_result_is_reviewed_with_input_signals(region):
    d, client = agent_deps([("RequestInfo", {"field": "size", "reason": "크기를 알려 주세요."})])
    d["animal"] = FakeAnimal(pages=[[]])
    run = search(d, {**SUFFICIENT, "region": region})
    assert run["candidates"] == [] and run["status"] == "completed"
    assert run["agent_request"]["field"] == "size"
    assert run["confidence"]["reasons"] == ["empty_result"]
    assert run["confidence"]["signals"]["color_given"] and run["confidence"]["signals"]["sex_given"]
    assert run["issues"] == [] and "reflect" not in run["trace"]
    assert "원본_공고_없음" in client.calls[0][1].content
    assert len(d["animal"].calls) == 1


def test_empty_breed_filter_can_be_relaxed_and_reviewed_again():
    d, client = agent_deps([("RelaxCondition", {"field": "breed", "reason": "품종 표기가 다를 수 있어요."})])
    d["animal"] = FakeAnimal(pages=[[api_item(1, kindNm="말티즈")]])
    run = search(d, {**SUFFICIENT, "region": "경기도", "breed": "푸들"})
    assert run["status"] == "completed" and len(run["candidates"]) == 1
    assert tools_used(run) == ["relax_condition", "finish"]
    assert run["agent_decision"]["reruns"] == 1 and "breed" not in run["criteria"]
    assert "조건_필터" in client.calls[0][1].content
    assert run["issues"] == [] and len(d["animal"].calls) == 1


def test_empty_radius_can_be_widened_by_agent():
    from .test_radius import base, items, kakao

    d, client = agent_deps([("WidenRadius", {"reason": "조회된 공고를 더 넓은 반경에서 확인해요."})])
    d["animal"] = FakeAnimal(pages=[items("서울특별시 노원구")])
    d["kakao"] = kakao()
    run = search(d, base(days=2))
    assert run["status"] == "completed" and run["candidates"]
    assert tools_used(run) == ["widen_radius", "finish"]
    assert "반경_필터" in client.calls[0][1].content
    assert run["agent_decision"]["reruns"] == 1 and len(d["animal"].calls) == 1


def test_agent_may_finish_empty_result_without_unresolved_issue():
    d, _ = agent_deps()
    d["animal"] = FakeAnimal(pages=[[]])
    run = search(d, {**SUFFICIENT, "region": "경기도"})
    assert run["status"] == "completed" and run["end_reason"] == "empty_result"
    assert run["issues"] == [] and tools_used(run) == ["finish"]


def test_empty_result_falls_back_to_existing_question_when_agent_fails():
    d, client = agent_deps(error=TimeoutError())
    d["animal"] = FakeAnimal(pages=[[]])
    run = search(d, {**SUFFICIENT, "region": "경기도"})
    assert len(client.calls) == 1 and run["agent_decision"]["source"] == "llm_error"
    assert run["status"] == "awaiting_input" and run["questions"][0]["field"] == "region"
    assert "reflect" in run["trace"] and run["criteria"]["region"] == "경기도"


def test_missing_input_and_api_failure_do_not_call_review_agent():
    d, client = agent_deps()
    assert search(d, {"species": "dog"})["status"] == "awaiting_input"
    d["animal"] = FakeAnimal(errors=["animal_auth"])
    run = search(d, SUFFICIENT)
    assert run["status"] == "failed" and run["error"]["code"] == "animal_auth"
    assert client.calls == []


def test_cached_sufficient_result_gets_fresh_review_without_new_retrieval():
    async def scenario():
        d, client = agent_deps()
        d["animal"] = FakeAnimal(pages=[[api_item(1)]])
        d["search_cache"] = SearchCache(fakeredis.FakeAsyncRedis())
        first = await run_search(d, "owner", {"criteria": SUFFICIENT})
        second = await run_search(d, "owner", {"criteria": SUFFICIENT})
        assert not first["cache_hit"] and second["cache_hit"]
        assert len(client.calls) == 2 and second["agent_decision"]["source"] == "llm"
        assert len(d["animal"].calls) == len(d["embedder"].calls) == 1
        assert second["candidates"] == first["candidates"] and second["tool_call_count"] == 1
        assert second["trace"][0] == "cache_hit" and "agent" in second["trace"]
        assert "raw_items" not in second and "semantic_scores" not in second
        snapshot = await d["search_cache"].get(first["cache_key"])
        assert "agent_request" not in snapshot and "agent_decision" not in snapshot
        assert snapshot["raw_items"] and snapshot["semantic_scores"]
    asyncio.run(scenario())


def test_cached_empty_result_uses_current_thread_question_limits():
    async def scenario():
        question = ("RequestInfo", {"field": "size", "reason": "크기를 알려 주세요."})
        d, client = agent_deps([question, question])
        d["animal"] = FakeAnimal(pages=[[]])
        d["search_cache"] = SearchCache(fakeredis.FakeAsyncRedis())
        first = await run_search(d, "owner", {"criteria": SUFFICIENT})
        second = await run_search(d, "owner", {"criteria": SUFFICIENT, "thread_id": first["thread_id"]})
        assert first["agent_request"]["field"] == "size"
        assert second["cache_hit"] and second["agent_request"] is None
        assert second["agent_decision"]["log"][1]["ok"] is False
        assert len(client.calls) == 3 and len(d["animal"].calls) == 1
    asyncio.run(scenario())


def test_agent_changes_do_not_pollute_cached_base_result():
    async def scenario():
        d, client = agent_deps([("UpdateFeatures", {"colors": ["흰색"], "reason": "설명의 털색을 반영해요."})])
        d["animal"] = FakeAnimal(pages=[[api_item(1)]])
        d["search_cache"] = SearchCache(fakeredis.FakeAsyncRedis())
        criteria = {**MIXED, "color": "갈색"}
        first = await run_search(d, "owner", {"criteria": criteria})
        second = await run_search(d, "owner", {"criteria": criteria})
        assert first["criteria"]["color"] == "흰색"
        thread = await d["store"].get("owner", "thread", first["thread_id"])
        assert thread["criteria"]["color"] == "갈색"  # 자동 수정은 사용자가 확인한 조건으로 저장하지 않는다.
        assert second["cache_hit"] and second["criteria"]["color"] == "갈색"
        assert second["agent_decision"]["reruns"] == 0
        assert len(client.calls) == 3 and len(d["animal"].calls) == 1
    asyncio.run(scenario())


def test_parallel_cached_searches_each_get_review_and_fetch_only_once():
    async def scenario():
        d, client = agent_deps()
        d["animal"] = FakeAnimal(pages=[[api_item(1)]])
        d["search_cache"] = SearchCache(fakeredis.FakeAsyncRedis())
        runs = await asyncio.gather(*(run_search(d, "owner", {"criteria": SUFFICIENT}) for _ in range(3)))
        assert sum(r["cache_hit"] for r in runs) == 2
        assert all(r["agent_decision"]["source"] == "llm" for r in runs)
        assert len(client.calls) == 3 and len(d["animal"].calls) == len(d["embedder"].calls) == 1
        assert len({r["thread_id"] for r in runs}) == 3
    asyncio.run(scenario())


def test_search_summary_exposes_only_stage_counts():
    summary = SA.search_summary({"total_count": 2, "raw_items": [{"care": {"tel": "secret"}}],
                                 "radius_items": [], "candidates": []})
    assert summary["빈_결과_원인"] == "반경_필터"
    assert "secret" not in json.dumps(summary)
