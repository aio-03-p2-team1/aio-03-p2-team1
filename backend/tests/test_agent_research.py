"""실제 공고 재검색 경로. LLM·공공 API는 모의 클라이언트/transport로 대체한다."""

import asyncio
from copy import deepcopy

import fakeredis
import httpx
import pytest

from backend.agent import graph, search_agent as SA
from backend.agent.runner import run_search
from backend.agent.search_cache import SearchCache

from .conftest import FakeAnimal, FakeEmbedder, api_item
from .test_animal_api import api, ok_body
from .test_graph import OWNER, START, deps, search
from .test_search_agent import MIXED, SUFFICIENT, agent_deps, tools_used


async def resolve_code(species, code):
    return {"kind_code": code, "name": "푸들"}


class ColorEmbedder(FakeEmbedder):
    async def embed(self, texts):
        self.calls.append(texts)
        return [[0., 1.] if "흰색" in text else [1., 0.] for text in texts]


@pytest.mark.parametrize("tool", [("RelaxCondition", {"field": "breed", "reason": "품종을 풀어요."}),
                                  ("SearchNotices", {"action": "relax_breed", "reason": "API 품종 필터를 풀어요."})])
def test_user_breed_is_never_relaxed_or_requeried(tool):
    """사용자가 고른 품종은 에이전트가 풀거나 다시 조회하지 않는다(질문 대상도 아님)."""
    async def scenario():
        queries = []

        def handler(request):
            queries.append(dict(request.url.params))
            raws = [] if request.url.params.get("kind") else [api_item(3, kindNm="믹스견", colorCd="흰색")]
            return httpx.Response(200, json=ok_body(raws))

        d, client = agent_deps([tool])
        d["animal"] = animal = api(handler)
        d["breed_normalizer"] = type("Normalizer", (), {"resolve_code": staticmethod(resolve_code)})()
        try:
            run = await run_search(d, OWNER, {"criteria": {**MIXED, "breed_code": "poodle-code"}})
            assert [q.get("kind") for q in queries] == ["poodle-code"]  # 품종 없는 재조회 없음
            assert run["criteria"]["breed_code"] == "poodle-code" and run["criteria"]["breed"] == "푸들"
            assert not any(c.get("breed") == "믹스견" for c in run.get("candidates") or [])
            first = run["agent_decision"]["log"][1]
            assert first["ok"] is False
            assert all(q.get("field") != "breed" for q in run.get("questions") or [])
            assert "relax_breed" not in client.calls[0][1].content.split("선택_가능_재검색")[1][:80]
        finally:
            await animal.aclose()
    asyncio.run(scenario())


def test_next_page_fetches_new_candidate_and_only_embeds_new_items(monkeypatch):
    monkeypatch.setattr(graph, "ROWS_PER_PAGE", 2)
    d, client = agent_deps([("SearchNotices", {"action": "next_page", "reason": "아직 조회하지 않은 공고가 있어요."})])
    d["animal"] = FakeAnimal(pages=[[api_item(1), api_item(2), api_item(3, colorCd="흰색")]])
    d["embedder"] = ColorEmbedder()
    run = search(d, {"species": "dog", "region": "전체", "lost_date": START, "description": "흰색"})
    assert [q["page"] for q in d["animal"].calls] == [1, 2]
    assert run["candidates"][0]["id"].endswith("00003")
    assert run["scope"]["pages_fetched"] == 2 and run["scope"]["fetched_rows"] == 3
    assert run["scope"]["complete"] and len(client.calls) == 2
    assert [len(texts) for texts in d["embedder"].calls] == [3, 2]
    assert tools_used(run) == ["search_notices", "finish"]


def test_api_research_is_once_per_run_even_if_more_pages_remain(monkeypatch):
    monkeypatch.setattr(graph, "ROWS_PER_PAGE", 2)
    tool = ("SearchNotices", {"action": "next_page", "reason": "다른 공고도 확인해요."})
    d, _ = agent_deps([tool, tool])
    d["animal"] = FakeAnimal(pages=[[api_item(i) for i in range(5)]])
    d["embedder"] = ColorEmbedder()
    run = search(d, {"species": "dog", "region": "전체", "lost_date": START, "description": "흰색"})
    assert len(d["animal"].calls) == 2 and run["agent_decision"]["researches"] == 1
    searches = [x for x in run["agent_decision"]["log"] if x.get("tool") == "search_notices"]
    assert searches[0]["ok"] and searches[1]["ok"] is False
    assert run["scope"]["fetched_rows"] == 4 and not run["scope"]["complete"]


def test_sufficient_results_do_not_trigger_research(monkeypatch):
    monkeypatch.setattr(graph, "ROWS_PER_PAGE", 2)
    d, _ = agent_deps([("SearchNotices", {"action": "next_page", "reason": "더 찾아요."})])
    d["animal"] = FakeAnimal(pages=[[api_item(i) for i in range(3)]])
    run = search(d, SUFFICIENT)
    assert run["confidence"]["low"] is False and len(d["animal"].calls) == 1
    assert run["agent_decision"]["researches"] == 0
    assert run["agent_decision"]["log"][1]["ok"] is False


def test_region_expansion_waits_for_explicit_user_followup():
    class RegionalAnimal(FakeAnimal):
        async def search(self, **kwargs):
            self.pages = [[]] if kwargs["region_code"] else [[api_item(3)]]
            return await super().search(**kwargs)

    d, client = agent_deps([("SearchNotices", {"action": "widen_region", "reason": "다른 지역 공고도 확인이 필요해요."})])
    d["animal"] = RegionalAnimal()
    before = search(d, {**SUFFICIENT, "region": "서울특별시"})
    assert before["status"] == "awaiting_input" and before["questions"][0]["field"] == "region"
    assert before["scope"]["region"] == "서울특별시" and before["criteria"]["region"] == "서울특별시"
    assert len(d["animal"].calls) == 1 and d["animal"].calls[0]["region_code"] == "6110000"
    assert before["agent_decision"]["researches"] == 0 and len(client.calls) == 1
    after = search(d, {"region": "전체", "radius_step": 3}, thread_id=before["thread_id"])
    assert after["status"] == "completed" and after["candidates"]
    assert len(d["animal"].calls) == 2 and d["animal"].calls[1]["region_code"] is None
    assert after["radius"]["reason"] == "whole_region"
    for field in ("species", "start_date", "end_date"):
        assert before["criteria"][field] == after["criteria"][field]


@pytest.mark.parametrize("error,retries,search_calls", [("animal_auth", 0, 2), ("animal_timeout", 2, 4)])
def test_failed_research_keeps_previous_candidates_and_scope(monkeypatch, error, retries, search_calls):
    monkeypatch.setattr(graph, "ROWS_PER_PAGE", 2)
    d, client = agent_deps([("SearchNotices", {"action": "next_page", "reason": "다음 공고를 확인해요."})])
    d["animal"] = FakeAnimal(pages=[[api_item(i) for i in range(3)]], errors=[None, error, error, error])
    d["embedder"] = ColorEmbedder()
    run = search(d, {"species": "dog", "region": "전체", "lost_date": START, "description": "흰색"})
    assert run["status"] == "partial" and run["error"]["code"] == error
    assert len(run["candidates"]) == 2 and run["scope"]["pages_fetched"] == 1
    assert run["scope"]["fetched_rows"] == 2 and run["scope"]["total_count"] == 3
    assert run["retry_count"] == retries and len(d["animal"].calls) == search_calls
    assert run["agent_decision"]["source"] == "tool_error" and run["agent_decision"]["researches"] == 1
    assert len(client.calls) == 1  # 실패를 분석하는 별도 성찰 LLM을 부르지 않는다.


def query_state():
    criteria = {"region": "서울특별시", "species": "dog", "start_date": START, "end_date": START,
                "breed": "푸들", "breed_code": "poodle-code"}
    return {"criteria": criteria, "confidence": {"low": True}, "raw_items": [], "candidates": [],
            "pages_fetched": 1, "total_count": 0,
            "search_query": {"region_code": "6110000", "species": "dog", "start": START, "end": START, "kind": "poodle-code"}}


def paged_state():
    state = query_state()
    state.update(raw_items=[{"id": "a"}], total_count=5)
    return state


def test_llm_cannot_supply_dates_region_species_or_page_to_api():
    state = paged_state()
    original = deepcopy(state)
    out = SA.execute_tool("search_notices", {"action": "next_page", "region_code": "evil", "start": "1900-01-01",
                                           "end": "2999-01-01", "species": "cat", "page": 999, "kind": None,
                                           "approved": True}, state, {})
    query = out["update"]["agent_search_plan"]["query"]
    assert query == state["search_query"]  # 품종 필터(kind)를 포함해 조회 조건은 그대로
    assert out["update"]["agent_search_plan"]["page"] == 2 and state == original
    assert set(SA.SearchNotices.model_fields) == {"action", "reason"}


@pytest.mark.parametrize("action", ["next_page", "relax_breed", "widen_period", "unknown"])
def test_unavailable_or_unknown_research_actions_are_rejected(action):
    out = SA.execute_tool("search_notices", {"action": action}, query_state(), {})
    assert out["content"]["ok"] is False and out["next"] is None and not out["update"]


def test_research_obeys_global_tool_budget_without_calling_api():
    d = deps(FakeAnimal(), max_tool_calls=10)
    state = paged_state()
    queued = SA.execute_tool("search_notices", {"action": "next_page"}, state, {})["update"]
    state.update(queued, tool_calls=[{}] * 10)
    out = asyncio.run(graph.research(state, {"configurable": d}))
    assert out["error"]["code"] == "tool_budget" and d["animal"].calls == []
    assert "criteria" not in out and "raw_items" not in out


def test_cache_keeps_original_query_and_review_result(monkeypatch):
    monkeypatch.setattr(graph, "ROWS_PER_PAGE", 2)

    async def scenario():
        research = ("SearchNotices", {"action": "next_page", "reason": "아직 조회하지 않은 공고가 있어요."})
        finish = ("Finish", {"note": "후보를 확인했습니다."})
        d, _ = agent_deps([research, finish])
        d["animal"] = FakeAnimal(pages=[[api_item(1), api_item(2), api_item(3, colorCd="흰색")]])
        d["embedder"] = ColorEmbedder()
        d["search_cache"] = SearchCache(fakeredis.FakeAsyncRedis())
        request = {"criteria": {"species": "dog", "region": "전체", "lost_date": START, "description": "흰색"}}
        first = await run_search(d, OWNER, request)
        second = await run_search(d, OWNER, request)
        assert not first["cache_hit"] and second["cache_hit"] and second["review_cache_hit"]
        assert first["agent_decision"]["researches"] == 1
        # 두 번째는 같은 맥락의 검토 결과를 캐시에서 꺼내 재조회 API 도 다시 부르지 않는다.
        assert [q["page"] for q in d["animal"].calls] == [1, 2]
        snapshot = await d["search_cache"].get(first["cache_key"])
        assert snapshot["pages_fetched"] == 1  # 기본 캐시는 에이전트 재조회 전 상태
        assert "agent_search_plan" not in snapshot and "agent_researches" not in snapshot
    asyncio.run(scenario())


def test_structural_fixes_remain_deterministic_before_agent_review():
    d, client = agent_deps()
    d["animal"] = FakeAnimal(pages=[[api_item(1), api_item(1)]])
    run = search(d, MIXED)
    assert len(run["candidates"]) == 1 and run["reflections"][0]["strategy"] == "dedupe_and_rerank"
    assert len(client.calls) == 1 and run["trace"].index("reflect") < run["trace"].index("agent")


def test_breed_relaxation_is_not_offered_or_applied():
    state = query_state()
    local = SA.execute_tool("relax_condition", {"field": "breed"}, state, {})
    assert local["content"]["ok"] is False and not local["update"] and not local["done"]
    assert state["criteria"]["breed_code"] == "poodle-code"
    assert SA.search_summary(state)["API_품종_필터"] is True
    assert "relax_breed" not in SA.research_options(state)
