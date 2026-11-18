"""실제 LLM 정책 평가와 검색 지연 측정. 운영 저장소에는 쓰지 않는다.

python -m scripts.benchmark_search_agent --probe
python -m scripts.benchmark_search_agent --repeats 3 --live-searches

정책 평가는 고정 공고/점수와 실제 채팅 모델을 사용한다. 실종 동물 식별 정확도는 평가하지 않는다.
실제 검색은 공공 API·특징 추출·임베딩·검토 모델을 호출하고 저장소/Redis만 메모리로 격리한다.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
import json
import logging
import math
import os
from pathlib import Path
import statistics
import subprocess
import time
from types import SimpleNamespace

import fakeredis
from langchain_core.messages import HumanMessage, SystemMessage

from backend.normalization.criteria import normalize
from backend.agent.embeddings import Embedder
from backend.agent.graph import REVIEW_GRAPH
from backend.agent.llm import FeatureExtractor, classify
from backend.agent.ranking import CONFIDENCE_VERSION, fuse_rrf, rank
from backend.agent.runner import run_search
from backend.agent.search_agent import AGENT_PROMPT_VERSION, SearchAgent
from backend.agent.search_cache import SearchCache
from backend.config import Settings
from backend.storage.sqlite import SqliteStore
from backend.timeutil import KST, kst_today
from backend.tools.animal_api import AnimalApi
from backend.tools.kakao import KakaoGeocoder


class MeasuredAgent:
    def __init__(self, agent, *, max_calls):
        self.agent, self.max_calls = agent, max_calls
        self.calls = []
        self.model = agent.model

    async def step(self, messages):
        if len(self.calls) >= self.max_calls:
            raise RuntimeError("benchmark_call_budget")
        record = {}
        self.calls.append(record)
        started = time.perf_counter()
        try:
            reply = await self.agent.step(messages)
            record.update(ok=True, tools=[c["name"] for c in reply.tool_calls],
                          model=(reply.response_metadata or {}).get("model_name"),
                          usage=reply.usage_metadata or {})
            return reply
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            body = getattr(exc, "body", None)
            record.update(ok=False, error_type=type(exc).__name__, status=status,
                          error_code=classify(status, body if isinstance(body, dict) else None) if status else None)
            raise
        finally:
            record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)


def timing(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "mean_ms": None, "median_ms": None, "p95_ms": None}
    return {"n": len(values), "mean_ms": round(statistics.mean(values), 2),
            "median_ms": round(statistics.median(values), 2),
            "p95_ms": round(values[math.ceil(len(values) * .95) - 1], 2)}


def fixture_cases():
    today = kst_today()
    basic = {"species": "dog", "region": "전체", "lost_date": (today - timedelta(days=2)).isoformat(),
             "color": "갈색", "sex": "F", "size": "소형", "description": "갈색 곱슬털 암컷"}
    item = {"id": "fixture-1", "species": "dog", "breed": "푸들", "color": "갈색", "sex": "F",
            "size": "소형", "happen_date": today.isoformat(), "special_mark": "갈색 곱슬털 암컷", "care": {}}
    mixed = {**basic, "color": "흰색", "description": "믹스견 흰색", "sex": "", "size": ""}
    twins = [{**item, "id": f"fixture-{i}", "breed": "믹스견", "color": "흰색", "sex": "Q",
              "size": "", "special_mark": "흰색 믹스견"} for i in (1, 2, 3)]
    return [
        {"id": "sufficient", "label": "충분한 결과는 추가 질문·수정 없이 확정", "criteria": basic,
         "items": [item], "first": {"finish"}, "final": {"finish"}, "reruns": 0},
        {"id": "ambiguous", "label": "구분하기 어려운 믹스견은 허용된 사진·정보 요청", "criteria": mixed,
         "items": twins, "first": {"request_photo", "request_info"},
         "final": {"request_photo", "request_info"}},
        {"id": "empty_source", "label": "원본 공고 없음·입력 충분이면 무의미한 수정 없이 종료",
         "criteria": basic, "items": [], "photo": {"suitable": True, "species": "dog", "colors": ["갈색"]},
         "first": {"finish"}, "final": {"finish"}, "reruns": 0},
        {"id": "empty_breed", "label": "불확실한 품종 필터로 0건이면 품종 완화 후 후보 복구",
         "criteria": {**basic, "breed": "푸들", "description": "갈색 곱슬털 암컷. 푸들로 알고 있지만 품종은 확실하지 않아요."},
         "items": [{**item, "breed": "믹스견"}], "first": {"relax_condition"}, "final": {"finish"},
         "recover": True},
        {"id": "empty_radius", "label": "반경 밖에만 공고가 있으면 허용된 반경 확대 후 후보 복구",
         "criteria": {**basic, "lost_place": "서울특별시 강서구", "radius_step": 2}, "items": [item],
         "radius_empty": True, "first": {"widen_radius"}, "final": {"finish"}, "recover": True},
        {"id": "declined", "label": "질문 한도·사용자 거절을 지키고 반복 요청 없이 종료", "criteria": mixed,
         "items": twins, "history": {"photo_requests": 1, "info_requests": 2,
                                       "asked_fields": ["sex", "size"], "declined": ["photo", "color", "marks"]},
         "first": {"finish"}, "final": {"finish"}, "reruns": 0},
    ]


def fixture_state(case):
    criteria, missing, errors = normalize(case["criteria"])
    if missing or errors:
        raise ValueError("invalid_benchmark_fixture")
    raw = deepcopy(case["items"])
    scores = {item["id"]: .9 - i * .001 for i, item in enumerate(raw)}
    radius = {"applied": False}
    filtered = None
    if case.get("radius_empty"):
        radius = {"applied": True, "step": 2, "max_step": 3, "radius_km": 20,
                  "next_radius_km": None, "excluded": len(raw), "inside": 0, "unknown": 0}
        filtered = []
    candidates = rank(raw if filtered is None else filtered, criteria)
    return {"criteria": criteria, "request": deepcopy(case["criteria"]), "raw_items": raw,
            "radius_items": filtered, "radius": radius, "semantic_scores": scores,
            "candidates": fuse_rrf(candidates, scores), "total_count": len(raw), "pages_fetched": 1,
            "fetched_at": datetime.now(KST).isoformat(), "data_source": "fixture",
            "photo_features": case.get("photo"), "agent_history": case.get("history", {}),
            "reflection_enabled": True, "reflection_count": 0, "trace": [], "tool_calls": [], "reflections": []}


def score_policy(case, result):
    decision = result.get("agent_decision") or {}
    calls = [x for x in decision.get("log") or [] if x.get("tool")]
    accepted = [x for x in calls if x.get("ok")]
    checks = {
        "actual_llm_completed": decision.get("source") == "llm",
        "first_strategy": bool(accepted) and accepted[0]["tool"] in case["first"],
        "final_action": decision.get("final_tool") in case["final"],
        "no_rejected_calls": not any(x.get("ok") is False for x in calls),
        "no_tool_error": not result.get("error"),
    }
    if "reruns" in case:
        checks["no_unnecessary_reruns"] = decision.get("reruns", 0) == case["reruns"]
    if case.get("recover"):
        checks["candidate_recovered"] = bool(result.get("candidates"))
    return {"pass": all(checks.values()), "checks": checks}


def summarize(rows, calls):
    grouped = {}
    for case_id in sorted({r["case"] for r in rows}):
        group = [r for r in rows if r["case"] == case_id]
        good = sum(r.get("assessment", {}).get("pass", False) for r in group)
        signatures = Counter((tuple(c["tool"] for c in r.get("tools", [])), r.get("final_tool")) for r in group)
        grouped[case_id] = {"runs": len(group), "passes": good,
                            "pass_rate": round(good / len(group), 4),
                            "action_sequence_consistency": round(max(signatures.values()) / len(group), 4),
                            "elapsed": timing([r["elapsed_ms"] for r in group]),
                            "llm_elapsed": timing([r["llm_elapsed_ms"] for r in group])}
    return {"cases": grouped, "attempted_model_calls": len(calls),
            "successful_model_calls": sum(bool(c.get("ok")) for c in calls),
            "model_call_elapsed": timing([c["elapsed_ms"] for c in calls]),
            "input_tokens": sum((c.get("usage") or {}).get("input_tokens", 0) for c in calls),
            "output_tokens": sum((c.get("usage") or {}).get("output_tokens", 0) for c in calls)}


def write_report(path, report, agent):
    report["summary"] = summarize(report["policy_runs"], agent.calls)
    report["model_calls"] = agent.calls
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def live_searches(settings, llm, agent, report, output):
    if not settings.animal_api_key:
        report["live_skipped"] = "animal_key_missing"
        return
    animal = AnimalApi(settings.animal_api_base_url, settings.animal_api_key.get_secret_value(), timeout=30)
    embedder = Embedder(settings.openai_api_key.get_secret_value(), timeout=45)
    kakao = KakaoGeocoder(None)  # 이 측정은 위치 좌표화 없는 검색이며 카카오 지연은 포함하지 않는다.
    redis = fakeredis.FakeAsyncRedis()
    deps = {"settings": settings, "store": SqliteStore(":memory:"), "animal": animal, "embedder": embedder,
            "kakao": kakao, "llm": llm, "search_agent": agent, "search_cache": SearchCache(redis)}
    criteria = {"species": "dog", "region": "서울특별시", "lost_date": (kst_today() - timedelta(days=2)).isoformat(),
                "description": "갈색 곱슬털 암컷 소형견"}
    try:
        for label in ("live_uncached", "live_cached"):
            offset = len(agent.calls)
            started = time.perf_counter()
            try:
                run = await run_search(deps, "isolated-benchmark", {"criteria": criteria})
                row = {"case": label, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                       "status": run["status"], "error_code": (run.get("error") or {}).get("code"),
                       "cache_hit": run["cache_hit"], "data_source": run["data_source"], "scope": run.get("scope"),
                       "candidate_count": len(run.get("candidates") or []),
                       "decision": run.get("agent_decision"), "confidence": run.get("confidence"),
                       "tool_timings": [{k: c.get(k) for k in ("tool", "outcome", "ms", "count")}
                                        for c in run.get("tool_calls") or []]}
            except Exception as exc:
                row = {"case": label, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                       "error_type": type(exc).__name__, "error_code": getattr(exc, "code", None)}
            row["llm_elapsed_ms"] = round(sum(c["elapsed_ms"] for c in agent.calls[offset:]), 2)
            report["live_runs"].append(row)
            write_report(output, report, agent)
            print(json.dumps({k: row.get(k) for k in ("case", "elapsed_ms", "status", "cache_hit", "error_code")}), flush=True)
            if row.get("error_code") or row.get("error_type"):
                break
    finally:
        await animal.aclose()
        await embedder.aclose()
        await kakao.aclose()
        await redis.aclose()


async def main(args):
    os.environ["LANGSMITH_TRACING"] = "false"
    logging.basicConfig(level=logging.ERROR)
    settings = Settings(app_mode="local", storage_backend="sqlite", langsmith_tracing=False)
    if not settings.openai_api_key:
        print(json.dumps({"error": "OPENAI_API_KEY_missing"}))
        return 2
    llm = FeatureExtractor(settings.openai_api_key.get_secret_value(), settings.openai_model, timeout=45)
    agent = MeasuredAgent(SearchAgent(llm._client, settings.openai_model), max_calls=args.max_calls)
    output = Path(args.output)
    report = {"measured_at": datetime.now(KST).isoformat(), "model": settings.openai_model,
              "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "agent_prompt": AGENT_PROMPT_VERSION, "confidence_version": CONFIDENCE_VERSION,
              "policy_scope": "actual LLM; synthetic fixed notices and similarities; extraction/embedding/retrieval excluded",
              "live_scope": "actual public API, feature extraction, embeddings, agent; in-memory SQLite/FakeRedis; no Kakao/browser",
              "repeats": args.repeats, "max_agent_calls": args.max_calls,
              "model_call_scope": "agent decisions only; excludes feature extraction, embeddings and separate probe",
              "policy_runs": [], "live_runs": [], "rubrics": []}
    try:
        if args.probe:
            try:
                await agent.step([SystemMessage(content="연결 확인입니다. Finish 도구로 종료하세요."),
                                  HumanMessage(content="연결 확인")])
            except Exception:
                write_report(output, report, agent)
                print(json.dumps(agent.calls[-1]), flush=True)
                return 2
            write_report(output, report, agent)
            print(json.dumps(agent.calls[-1]), flush=True)
            return 0
        cases = fixture_cases()
        report["rubrics"] = [{k: sorted(v) if isinstance(v, set) else v for k, v in case.items()
                              if k not in ("items", "criteria", "photo", "history")} for case in cases]
        deps = {"settings": settings, "animal": SimpleNamespace(source="sample"), "embedder": None,
                "kakao": KakaoGeocoder(None), "search_agent": agent}
        for repetition in range(1, args.repeats + 1):
            for case in cases:
                if len(agent.calls) >= args.max_calls:
                    report["stopped"] = "model_call_budget"
                    break
                offset = len(agent.calls)
                started = time.perf_counter()
                result = await asyncio.wait_for(REVIEW_GRAPH.ainvoke(fixture_state(case),
                                                {"configurable": deps, "recursion_limit": 80}), timeout=120)
                decision = result.get("agent_decision") or {}
                row = {"case": case["id"], "repeat": repetition,
                       "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                       "llm_elapsed_ms": round(sum(c["elapsed_ms"] for c in agent.calls[offset:]), 2),
                       "final_tool": decision.get("final_tool"), "decision_source": decision.get("source"),
                       "reruns": decision.get("reruns"), "candidate_count": len(result.get("candidates") or []),
                       "tools": [x for x in decision.get("log") or [] if x.get("tool")],
                       "assessment": score_policy(case, result)}
                report["policy_runs"].append(row)
                write_report(output, report, agent)
                print(json.dumps({k: row[k] for k in ("case", "repeat", "elapsed_ms", "final_tool", "assessment")},
                                 ensure_ascii=False), flush=True)
                if agent.calls and agent.calls[-1].get("ok") is False:
                    report["stopped"] = "model_call_error"
                    break
            if report.get("stopped"):
                break
        if args.live_searches and not report.get("stopped"):
            await live_searches(settings, llm, agent, report, output)
        write_report(output, report, agent)
        print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
        return 0
    finally:
        await llm.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--max-calls", type=int, choices=range(1, 101), default=60)
    parser.add_argument("--live-searches", action="store_true")
    parser.add_argument("--output", default="docs/data/search-agent-live-2026-11-18.json")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
