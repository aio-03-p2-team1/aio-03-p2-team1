"""평가 스크립트의 채점·통계는 외부 호출 없이 검증한다."""

from scripts.benchmark_search_agent import score_policy, summarize, timing


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
