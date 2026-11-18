"""v4 단축 평가: 고정 정책 4건, 실제 검색 cold/warm 1쌍. 이전 버전은 재실행하지 않는다."""
import asyncio
from copy import deepcopy
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

from langchain_core.callbacks import AsyncCallbackHandler
import tiktoken

from backend.agent.graph import REVIEW_GRAPH
from backend.agent.llm import FeatureExtractor
from backend.agent.ranking import fuse_rrf, rank
from backend.agent.search_agent import AGENT_PROMPT_VERSION, SearchAgent
from backend.config import Settings
from backend.timeutil import KST
from backend.tools.kakao import KakaoGeocoder
from datetime import datetime
from scripts.benchmark_search_agent import MeasuredAgent, fixture_cases, fixture_state, live_searches, write_report

OUTPUT = Path("docs/data/search-agent-quick-2026-11-18.json")


def quick_summary(report):
    outcomes = {}
    for row in report["policy_runs"]:
        if row.get("excluded_from_quality"):
            continue
        checks = row["assessment"]["checks"]
        status = "pass" if row["assessment"]["pass"] else "fail"
        if not checks.get("llm_completed", True) and report.get("budget_stop"):
            status = "incomplete_budget"
        outcomes[row["case"]] = status
    tokens = report["chat_usage"]["total_tokens"]
    return {"policy_outcomes": outcomes, "chat_tokens": tokens,
            "reduction_vs_50405_agent_tokens_percent": round((1 - tokens / 50405) * 100, 2),
            "active_runtime_seconds": round(report["total_elapsed_ms"] / 1000, 2),
            "valid_speed_runs": [r for r in report["live_runs"] if not r.get("error")
                                 and (r.get("decision") or {}).get("source") == "llm"]}


class Budget(AsyncCallbackHandler):
    raise_error = True

    def __init__(self):
        self.used, self.started, self.calls, self.blocked = 0, {}, [], None
        self.encoding = tiktoken.get_encoding("o200k_base")

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        invocation = kwargs.get("invocation_params") or {}
        payload = {"messages": [[{"content": m.content, "calls": getattr(m, "tool_calls", [])} for m in group]
                                 for group in messages], "params": invocation}
        reserve = len(self.encoding.encode(json.dumps(payload, ensure_ascii=False, default=str))) + 1024 + 256
        if getattr(self, "fresh_reserve", None) and len(messages[0]) == 2:
            reserve = min(reserve, self.fresh_reserve)
        if len(self.calls) >= 9 or self.used + reserve > 20000:
            self.blocked = "token_or_call_budget"
            raise RuntimeError(self.blocked)
        self.started[run_id] = time.perf_counter()

    async def on_llm_end(self, response, *, run_id, **kwargs):
        message = response.generations[0][0].message
        usage = message.usage_metadata or {}
        total = usage.get("total_tokens")
        self.calls.append({"usage": usage, "elapsed_ms": round((time.perf_counter() - self.started.pop(run_id)) * 1000, 2)})
        if total is None:
            self.blocked = "usage_missing"
        else:
            self.used += total


class FixtureAnimal:
    source = "sample"

    def __init__(self, item):
        self.item, self.calls = item, []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(items=[deepcopy(self.item)], total_count=1001 if kwargs["page"] == 2 else 1,
                               fetched_at=datetime.now(KST).isoformat())


class FixedEmbedder:
    model = "fixed-fixture-vectors"

    async def embed(self, texts):
        return [[0., 1.] if "흰색" in t else [1., 0.] for t in texts]


def cases():
    normal, _, _, breed, *_ = fixture_cases()
    target = {**normal["items"][0], "id": "fixture-target", "color": "흰색", "special_mark": "흰색 곱슬털 암컷"}
    sufficient = fixture_state(normal)
    page = fixture_state({**normal, "criteria": {**normal["criteria"], "color": "흰색", "description": "흰색 곱슬털 암컷"},
                          "items": [{**normal["items"][0], "id": f"fixture-{i:04}"} for i in range(1000)]})
    page.update(total_count=1001, semantic_scores={i["id"]: .1 for i in page["raw_items"]})
    page["candidates"] = fuse_rrf(rank(page["raw_items"], page["criteria"]), page["semantic_scores"])
    breed_state = fixture_state({**breed, "items": []})
    region = fixture_state({**normal, "criteria": {**normal["criteria"], "region": "서울특별시"}, "items": []})
    region["criteria"].update(region_code="6110000", region_name="서울특별시")
    out = [("sufficient", sufficient, None), ("next_page", page, "next_page"),
           ("relax_breed", breed_state, "relax_breed"), ("widen_region", region, "widen_region")]
    for _, state, action in out:
        c = state["criteria"]
        state["search_query"] = {"region_code": c.get("region_code"), "species": c["species"],
                                  "start": c["start_date"], "end": c["end_date"],
                                  "kind": "fixture-code" if action == "relax_breed" else None}
        if action == "relax_breed":
            c["breed_code"] = "fixture-code"
    return out, target


async def main():
    os.environ["LANGSMITH_TRACING"] = "false"
    logging.basicConfig(level=logging.ERROR)
    settings = Settings(app_mode="local", storage_backend="sqlite", langsmith_tracing=False)
    budget = Budget()
    llm = FeatureExtractor(settings.openai_api_key.get_secret_value(), settings.openai_model, timeout=30)
    llm._client.callbacks = [budget]
    llm._client.max_tokens = 256
    agent = MeasuredAgent(SearchAgent(llm._client, settings.openai_model), max_calls=8)
    report = {"measured_at": datetime.now(KST).isoformat(), "model": settings.openai_model,
              "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "agent_prompt": AGENT_PROMPT_VERSION, "policy_runs": [], "live_runs": [],
              "limits": {"agent_calls": 8, "all_chat_calls": 9, "token_budget": 20000, "output_tokens_per_call": 256,
                         "deadline_seconds": 120, "input_reserve": "o200k estimate plus 1024 overhead tokens"},
              "scope": "policy: real LLM, fixed features/vectors and mock API; live pair: real API/extraction/embedding, memory storage, no Kakao/browser"}
    started = time.perf_counter()

    async def evaluate():
        scenarios, target = cases()
        for name, state, expected in scenarios:
            animal = FixtureAnimal(target)
            deps = {"settings": settings, "animal": animal, "embedder": FixedEmbedder(),
                    "kakao": KakaoGeocoder(None), "search_agent": agent}
            before, tick = len(agent.calls), time.perf_counter()
            result = await REVIEW_GRAPH.ainvoke(state, {"configurable": deps, "recursion_limit": 80})
            decision = result.get("agent_decision") or {}
            tools = [x for x in decision.get("log", []) if x.get("tool")]
            checks = {"llm_completed": decision.get("source") == "llm", "no_rejected_calls": all(t["ok"] for t in tools)}
            if expected:
                checks["strategy"] = bool(tools) and tools[0]["tool"] == "search_notices" and tools[0]["args"].get("action") == expected
                checks["effect"] = (result.get("status") == "awaiting_input" and not animal.calls
                                    and result["criteria"]["region"] == "서울특별시") if expected == "widen_region" else bool(result.get("candidates")) and len(animal.calls) == 1
            else:
                checks["finish_without_rerun"] = decision.get("final_tool") == "finish" and not decision.get("reruns")
            row = {"case": name, "elapsed_ms": round((time.perf_counter() - tick) * 1000, 2),
                   "llm_elapsed_ms": round(sum(c["elapsed_ms"] for c in agent.calls[before:]), 2),
                   "tools": tools, "final_tool": decision.get("final_tool"), "assessment": {"pass": all(checks.values()), "checks": checks}}
            report["policy_runs"].append(row)
            write_report(OUTPUT, report, agent)
            print(json.dumps({"case": name, "pass": row["assessment"]["pass"], "elapsed_ms": row["elapsed_ms"]}), flush=True)
            if budget.blocked or any(not c.get("ok") for c in agent.calls[before:]):
                return
        await live_searches(settings, llm, agent, report, OUTPUT)

    try:
        await asyncio.wait_for(evaluate(), timeout=120)
    except Exception as exc:
        report["stopped"] = type(exc).__name__
    finally:
        report.update(total_elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
                      chat_usage={"calls": budget.calls, "total_tokens": budget.used}, budget_stop=budget.blocked)
        report["quick_results"] = quick_summary(report)
        write_report(OUTPUT, report, agent)
        await llm.aclose()
    print(json.dumps({"policy_passes": sum(r["assessment"]["pass"] for r in report["policy_runs"]),
                      "policy_runs": len(report["policy_runs"]), "tokens": budget.used,
                      "agent_calls": len(agent.calls), "elapsed_ms": report["total_elapsed_ms"]}), flush=True)


async def finish_scope_speed():
    """기존 예산을 이어 쓰며 지역 확인과 cold/warm 속도를 같은 2회 호출로 측정한다."""
    from backend.agent.runner import run_search
    from backend.agent.embeddings import Embedder
    from backend.agent.search_cache import SearchCache
    from backend.storage.sqlite import SqliteStore
    from backend.timeutil import kst_today
    from backend.tools.animal_api import AnimalApi
    import fakeredis

    os.environ["LANGSMITH_TRACING"] = "false"
    logging.basicConfig(level=logging.ERROR)
    report = json.loads(OUTPUT.read_text(encoding="utf-8"))
    for row in report["policy_runs"]:
        preflight = any((r.get("error") or {}).get("code") == "embedding_not_configured"
                        and r["elapsed_ms"] == row["elapsed_ms"] for r in report["live_runs"])
        if row["case"] == "widen_region" and preflight:
            row["excluded_from_quality"] = "embedding-disabled preflight; no LLM call"
    budget = Budget()
    budget.used, budget.calls = report["chat_usage"]["total_tokens"], report["chat_usage"]["calls"]
    # 같은 v4의 짧은 첫 메시지는 실측 1,871~2,378 입력 토큰이었다. 3,000 토큰을 예약한다.
    budget.fresh_reserve = 3000
    settings = Settings(app_mode="local", storage_backend="sqlite", langsmith_tracing=False)
    llm = FeatureExtractor(settings.openai_api_key.get_secret_value(), settings.openai_model, timeout=30)
    llm._client.callbacks, llm._client.max_tokens = [budget], 256
    agent = MeasuredAgent(SearchAgent(llm._client, settings.openai_model), max_calls=8)
    agent.calls = report["model_calls"]
    animal = AnimalApi(settings.animal_api_base_url, settings.animal_api_key.get_secret_value(), timeout=15)
    embedder = Embedder(settings.openai_api_key.get_secret_value(), timeout=15)
    redis, store, kakao = fakeredis.FakeAsyncRedis(), SqliteStore(":memory:"), KakaoGeocoder(None)
    deps = {"settings": settings, "animal": animal, "store": store, "kakao": kakao, "llm": None,
            "embedder": embedder, "search_agent": agent, "search_cache": SearchCache(redis)}
    criteria = {"species": "dog", "region": "서울특별시", "lost_date": kst_today().isoformat(),
                "color": "검정", "sex": "M", "size": "소형", "description": "검정 수컷 꼬리짧음"}
    report["scope_speed_criteria"] = criteria
    started = time.perf_counter()

    async def pair():
        for phase in ("cold", "warm"):
            tick = time.perf_counter()
            result = await run_search(deps, "isolated-quick", {"criteria": criteria,
                                    "photo": {"suitable": True, "species": "dog", "colors": ["검정"], "sex": "M", "marks": ["꼬리짧음"]}})
            decision = result.get("agent_decision") or {}
            row = {"case": phase, "elapsed_ms": round((time.perf_counter() - tick) * 1000, 2),
                   "scope": result.get("scope"), "cache_hit": result["cache_hit"], "status": result["status"],
                   "decision": decision, "error": result.get("error")}
            report["live_runs"].append(row)
            if phase == "cold":
                tools = [t for t in decision.get("log", []) if t.get("tool")]
                valid = (decision.get("source") == "llm" and bool(tools) and tools[0]["tool"] == "search_notices"
                         and tools[0]["args"].get("action") == "widen_region" and result["status"] == "awaiting_input")
                report["policy_runs"].append({"case": "widen_region", "elapsed_ms": row["elapsed_ms"],
                    "llm_elapsed_ms": agent.calls[-1]["elapsed_ms"], "tools": tools,
                    "final_tool": decision.get("final_tool"), "assessment": {"pass": valid, "checks": {"scope_confirmation": valid}}})
            write_report(OUTPUT, report, agent)
            print(json.dumps({k: row[k] for k in ("case", "elapsed_ms", "cache_hit", "status")}), flush=True)

    try:
        await asyncio.wait_for(pair(), timeout=max(1, 120 - report["total_elapsed_ms"] / 1000))
    except Exception as exc:
        report["resume_stop"] = type(exc).__name__
    finally:
        report["total_elapsed_ms"] += round((time.perf_counter() - started) * 1000, 2)
        report["chat_usage"] = {"calls": budget.calls, "total_tokens": budget.used}
        report["resume_budget_stop"] = budget.blocked
        report["scope_speed_note"] = "real API and embeddings; fixed input/photo traits, no feature extraction; no Kakao/browser; earlier embedding-disabled preflight failures retained"
        report["limits"]["resume_fresh_prompt_reserve"] = 3000
        report["quick_results"] = quick_summary(report)
        write_report(OUTPUT, report, agent)
        await llm.aclose()
        await animal.aclose()
        await embedder.aclose()
        await redis.aclose()
        await store.aclose()
        await kakao.aclose()
    print(json.dumps({"tokens": budget.used, "paid_chat_calls": len(budget.calls),
                      "active_elapsed_ms": report["total_elapsed_ms"]}), flush=True)


if __name__ == "__main__":
    asyncio.run(finish_scope_speed() if "--finish-scope-speed" in sys.argv else main())
