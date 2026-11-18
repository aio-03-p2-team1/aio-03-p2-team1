"""평가 스크립트의 채점·통계는 외부 호출 없이 검증한다."""

import asyncio
from types import SimpleNamespace

import pytest

from scripts.benchmark_search_agent import score_policy, summarize, timing
from scripts.compare_search_agent import Meter, TimedService, aggregate, digest
from scripts.benchmark_agent_quick import quick_summary


def test_timing_uses_nearest_rank_p95_and_handles_no_measurement():
    assert timing([]) == {"n": 0, "mean_ms": None, "median_ms": None, "p95_ms": None}
    assert timing(list(range(1, 101))) == {"n": 100, "mean_ms": 50.5, "median_ms": 50.5, "p95_ms": 95}


def test_policy_does_not_count_fallback_or_rejected_call_as_success():
    case = {"first": {"finish"}, "final": {"finish"}, "reruns": 0}
    result = {"agent_decision": {"source": "llm", "final_tool": "finish", "reruns": 0,
                                  "log": [{"tool": "finish", "ok": True}]}}
    assert score_policy(case, result)["pass"]
    result["agent_decision"]["source"] = "llm_error"
    assert not score_policy(case, result)["pass"]
    result["agent_decision"]["source"] = "llm"
    result["agent_decision"]["log"].insert(0, {"tool": "request_photo", "ok": False})
    assert not score_policy(case, result)["pass"]


def test_recovery_requires_result_not_only_a_tool_call():
    case = {"first": {"relax_condition"}, "final": {"finish"}, "recover": True}
    result = {"agent_decision": {"source": "llm", "final_tool": "finish",
                                  "log": [{"tool": "relax_condition", "ok": True}, {"tool": "finish", "ok": True}]}}
    assert not score_policy(case, result)["pass"]
    result["candidates"] = [{"id": "fixture-1"}]
    assert score_policy(case, result)["pass"]


def test_summary_keeps_failed_runs_in_denominator_and_counts_usage():
    base = {"case": "one", "elapsed_ms": 100, "llm_elapsed_ms": 90, "tools": [], "final_tool": "finish"}
    summary = summarize([{**base, "assessment": {"pass": True}}, {**base, "assessment": {"pass": False}}],
                        [{"elapsed_ms": 80, "ok": True, "usage": {"input_tokens": 100, "output_tokens": 20}},
                         {"elapsed_ms": 10, "ok": False}])
    assert summary["cases"]["one"]["pass_rate"] == .5
    assert summary["attempted_model_calls"] == 2 and summary["successful_model_calls"] == 1
    assert summary["input_tokens"] == 100 and summary["output_tokens"] == 20


def test_comparison_separates_versions_and_retains_invalid_run_counts():
    base = {"case": "public", "phase": "warm", "agent_calls": 0, "status": "completed"}
    rows = [{**base, "variant": "before", "elapsed_ms": 4, "cache_hit": True, "valid_measurement": True},
            {**base, "variant": "before", "elapsed_ms": 9000, "valid_measurement": False},
            {**base, "variant": "after", "elapsed_ms": 3000, "agent_calls": 1, "valid_measurement": True}]
    groups = {r["variant"]: r for r in aggregate(rows)}
    assert groups["before"]["runs"] == 2 and groups["before"]["valid_runs"] == 1
    assert groups["before"]["mean_ms"] == 4 and groups["before"]["cache_hits"] == 1
    assert groups["after"]["mean_ms"] == 3000 and groups["after"]["agent_calls"] == 1


def test_comparison_hash_ignores_dictionary_order_but_detects_different_inputs():
    assert digest({"criteria": {"sex": "F", "color": "갈색"}, "items": []}) == digest(
        {"items": [], "criteria": {"color": "갈색", "sex": "F"}})
    assert digest({"items": [{"id": "a"}]}) != digest({"items": [{"id": "b"}]})


def test_comparison_budget_prevents_extra_model_call():
    async def scenario():
        calls = []

        async def step(messages):
            calls.append(messages)
            return SimpleNamespace(usage_metadata={"input_tokens": 10})

        meter = Meter()
        agent = TimedService(SimpleNamespace(model="fake", step=step), "step", meter, "agent", budget=1)
        await agent.step([])
        with pytest.raises(RuntimeError, match="comparison_agent_budget"):
            await agent.step([])
        assert len(calls) == len(meter.events) == 1 and meter.events[0]["ok"]
    asyncio.run(scenario())


def test_quick_summary_keeps_budget_incomplete_and_excludes_preflight_from_quality():
    report = {"policy_runs": [
        {"case": "scope", "assessment": {"pass": False, "checks": {}}, "excluded_from_quality": "no model call"},
        {"case": "breed", "assessment": {"pass": False, "checks": {"llm_completed": False}}},
        {"case": "scope", "assessment": {"pass": True, "checks": {}}}],
        "live_runs": [{"error": {"code": "embedding_not_configured"}},
                      {"error": None, "decision": {"source": "llm"}, "elapsed_ms": 3000}],
        "budget_stop": "token_budget", "chat_usage": {"total_tokens": 18789}, "total_elapsed_ms": 35093}
    result = quick_summary(report)
    assert result["policy_outcomes"] == {"breed": "incomplete_budget", "scope": "pass"}
    assert len(result["valid_speed_runs"]) == 1 and result["reduction_vs_50405_agent_tokens_percent"] > 50
