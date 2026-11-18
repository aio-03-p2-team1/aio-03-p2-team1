"""적용 전/후 코드를 별도 프로세스에서 비교한다. 운영 서비스·작업 트리는 변경하지 않는다.

uv run python -X utf8 -m scripts.compare_search_agent --repeats 3

공공 API를 한 번 캡처한 동일 공고와 명시적인 모의 입력을 사용한다. 공고 HTTP 지연은 제외하고,
특징 추출·임베딩·에이전트는 실제 호출한다. SQLite와 Redis는 프로세스별 메모리 저장소다.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import version
import io
import json
import logging
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def aggregate(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["case"], row["phase"], row["variant"])].append(row)
    result = []
    for (case, phase, variant), group in sorted(groups.items()):
        times = [r["elapsed_ms"] for r in group if r.get("valid_measurement")]
        result.append({"case": case, "phase": phase, "variant": variant, "runs": len(group),
                       "valid_runs": len(times), "mean_ms": round(statistics.mean(times), 2) if times else None,
                       "median_ms": round(statistics.median(times), 2) if times else None,
                       "min_ms": min(times) if times else None, "max_ms": max(times) if times else None,
                       "agent_calls": sum(r["agent_calls"] for r in group),
                       "cache_hits": sum(bool(r.get("cache_hit")) for r in group),
                       "statuses": sorted({r.get("status", "error") for r in group})})
    return result


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Meter:
    def __init__(self):
        self.events = []

    async def invoke(self, category, callback, *args, **kwargs):
        started = time.perf_counter()
        event = {"category": category}
        self.events.append(event)
        try:
            result = await callback(*args, **kwargs)
            event["ok"] = True
            usage = getattr(result, "usage_metadata", None)
            if usage:
                event["usage"] = usage
            return result
        except Exception as exc:
            event.update(ok=False, error_type=type(exc).__name__, status=getattr(exc, "status_code", None))
            raise
        finally:
            event["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)


class TimedService:
    def __init__(self, service, method, meter, category, budget=None):
        self.service, self.method, self.meter = service, method, meter
        self.category, self.budget = category, budget
        self.model = service.model

    def __getattr__(self, name):
        if name != self.method:
            return getattr(self.service, name)

        async def measured(*args, **kwargs):
            if self.budget is not None and sum(e["category"] == self.category for e in self.meter.events) >= self.budget:
                raise RuntimeError("comparison_agent_budget")
            return await self.meter.invoke(self.category, getattr(self.service, self.method), *args, **kwargs)
        return measured


async def worker(args):
    # 이 프로세스의 backend 패키지는 이 경로에서만 읽는다. 이전 코드와 현재 코드를 섞지 않는다.
    sys.path.insert(0, str(Path(args.source_root).resolve()))
    import backend.agent.graph as graph_module
    from backend.agent.embeddings import Embedder
    from backend.agent.llm import FeatureExtractor, PROMPT_VERSION
    from backend.agent.runner import run_search
    from backend.agent.search_agent import AGENT_PROMPT_VERSION, SearchAgent
    from backend.agent.search_cache import SearchCache
    from backend.config import Settings
    from backend.storage.sqlite import SqliteStore
    from backend.tools.animal_api import Region, SearchPage
    from backend.tools.kakao import KakaoGeocoder
    import fakeredis

    settings = Settings(_env_file=ROOT / ".env", app_mode="local", storage_backend="sqlite", langsmith_tracing=False)
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    case = next(c for c in snapshot["cases"] if c["id"] == args.case)
    assert Path(graph_module.__file__).resolve().is_relative_to(Path(args.source_root).resolve())

    class FrozenAnimal:
        source = case["origin"]

        def __init__(self):
            self.calls = 0

        async def regions(self):
            return [Region(**r) for r in snapshot["regions"]]

        async def search(self, **params):
            self.calls += 1
            return SearchPage(items=deepcopy(case["items"]), total_count=len(case["items"]),
                              page=1, rows=params["rows"], fetched_at=snapshot["captured_at"], source=self.source)

    meter = Meter()
    llm = FeatureExtractor(settings.openai_api_key.get_secret_value(), settings.openai_model, timeout=45)
    embedder = Embedder(settings.openai_api_key.get_secret_value(), timeout=45)
    agent = SearchAgent(llm._client, settings.openai_model)
    redis = fakeredis.FakeAsyncRedis()
    store, animal, kakao = SqliteStore(":memory:"), FrozenAnimal(), KakaoGeocoder(None)
    deps = {"settings": settings, "store": store, "animal": animal, "kakao": kakao,
            "llm": TimedService(llm, "extract", meter, "features"),
            "embedder": TimedService(embedder, "embed", meter, "embedding"),
            "search_agent": TimedService(agent, "step", meter, "agent", args.max_agent_calls),
            "search_cache": SearchCache(redis)}
    rows = []
    try:
        for phase in ("cold", "warm"):
            offset, reads = len(meter.events), animal.calls
            started = time.perf_counter()
            row = {"case": case["id"], "phase": phase, "variant": args.variant, "repeat": args.repeat,
                   "input_origin": case["origin"], "input_sha256": digest(case), "public_api_http_calls": 0,
                   "model": settings.openai_model, "feature_prompt": PROMPT_VERSION, "agent_prompt": AGENT_PROMPT_VERSION}
            try:
                run = await run_search(deps, "isolated-comparison", {"criteria": case["criteria"],
                                                                   "photo": case.get("photo")})
                row.update(status=run["status"], error_code=(run.get("error") or {}).get("code"),
                           cache_hit=run["cache_hit"], review_cache_hit=run.get("review_cache_hit"),
                           candidate_count=len(run.get("candidates") or []),
                           top_id=(run.get("candidates") or [{}])[0].get("id") if run.get("candidates") else None,
                           decision=run.get("agent_decision"), confidence=run.get("confidence"),
                           questions=[q.get("field") for q in run.get("questions") or []],
                           trace=run["trace"])
            except Exception as exc:
                row.update(error_type=type(exc).__name__, error_code=getattr(exc, "code", None))
            row["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
            row["events"] = meter.events[offset:]
            row["agent_calls"] = sum(e["category"] == "agent" for e in row["events"])
            row["snapshot_reads"] = animal.calls - reads
            row["valid_measurement"] = (not row.get("error_type") and not row.get("error_code")
                                        and all(e.get("ok") for e in row["events"])
                                        and (not row.get("decision") or row["decision"].get("source") == "llm"))
            rows.append(row)
            save(Path(args.worker_output), rows)
            print(json.dumps({k: row.get(k) for k in ("case", "phase", "variant", "repeat", "elapsed_ms",
                                                     "status", "agent_calls", "valid_measurement")}), flush=True)
            if not row["valid_measurement"]:
                break
        return 0 if all(r["valid_measurement"] for r in rows) else 2
    finally:
        await llm.aclose()
        await embedder.aclose()
        await kakao.aclose()
        await store.aclose()
        await redis.aclose()


def snapshot_source(ref, directory):
    revision = subprocess.check_output(["git", "rev-parse", "--verify", ref + "^{commit}"], cwd=ROOT, text=True).strip()
    destination = directory / revision
    archive = subprocess.check_output(["git", "archive", "--format=zip", revision, "backend"], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        for name in zipped.namelist():
            if not (destination / name).resolve().is_relative_to(destination.resolve()):
                raise ValueError("unsafe_archive_path")
        zipped.extractall(destination)
    return revision, destination


async def capture_inputs(path):
    from backend.config import Settings
    from backend.tools.animal_api import AnimalApi
    from backend.timeutil import kst_today

    settings = Settings(app_mode="local", storage_backend="sqlite", langsmith_tracing=False)
    if not settings.openai_api_key or not settings.animal_api_key:
        raise RuntimeError("benchmark_keys_missing")
    animal = AnimalApi(settings.animal_api_base_url, settings.animal_api_key.get_secret_value(), timeout=30)
    today = kst_today()
    criteria = {"species": "dog", "region": "서울특별시", "lost_date": (today - timedelta(days=2)).isoformat(),
                "description": "갈색 곱슬털 암컷 소형견"}
    try:
        regions = await animal.regions()
        region = next(r for r in regions if r.name == criteria["region"])
        page = await animal.search(region_code=region.code, species="dog", start=today - timedelta(days=2),
                                   end=today, rows=1000)
    finally:
        await animal.aclose()
    # 연락처·보호소 주소·사진 URL은 비교에 필요하지 않아 보관하지 않는다.
    fields = ("id", "species", "breed", "color", "sex", "size", "weight", "age", "special_mark", "happen_date")
    items = [{**{k: item.get(k) for k in fields}, "care": {}} for item in page.items]
    mixed = [{"id": f"synthetic-{i}", "species": "dog", "breed": "믹스견", "color": "흰색", "sex": "Q",
              "happen_date": today.isoformat(), "special_mark": "흰색 믹스견", "care": {}} for i in range(3)]
    snapshot = {"captured_at": page.fetched_at, "model": settings.openai_model,
                "public_total_count": page.total_count, "public_snapshot_count": len(items),
                "regions": [{"code": region.code, "name": region.name}], "cases": [
                    {"id": "public_notices", "origin": "fixed_public_snapshot", "criteria": criteria, "items": items},
                    {"id": "ambiguous", "origin": "synthetic_fixture",
                     "criteria": {**criteria, "description": "믹스견 흰색"}, "items": mixed},
                    {"id": "empty", "origin": "synthetic_fixture",
                     "criteria": {**criteria, "color": "갈색", "sex": "F", "size": "소형",
                                  "description": "갈색 곱슬털 암컷"}, "items": [],
                     "photo": {"suitable": True, "species": "dog", "colors": ["갈색"]}},
                ]}
    save(path, snapshot)
    return snapshot


async def controller(args):
    workspace = ROOT / ".data" / "agent-comparison" / datetime.now(KST).strftime("%Y%m%d-%H%M%S")
    before_ref, before_root = snapshot_source(args.before, workspace)
    after_ref, after_root = snapshot_source("HEAD", workspace)
    snapshot_path = workspace / "inputs.json"
    snapshot = await capture_inputs(snapshot_path)
    report = {"measured_at": datetime.now(KST).isoformat(), "before_revision": before_ref, "after_revision": after_ref,
              "model": snapshot["model"], "snapshot_sha256": digest(snapshot),
              "inputs": snapshot,
              "public_snapshot_count": snapshot["public_snapshot_count"], "public_total_count": snapshot["public_total_count"],
              "scope": "real feature LLM, embeddings and agent; frozen identical notices; no public HTTP, Kakao, browser or production storage latency",
              "repeats": args.repeats, "max_agent_calls": args.max_agent_calls,
              "dependencies": {p: version(p) for p in ("langgraph", "langchain-openai", "openai", "fakeredis")},
              "rows": [], "summary": []}
    output = ROOT / args.output
    for repetition in range(1, args.repeats + 1):
        for case in snapshot["cases"]:
            variants = [("before", before_root), ("after", after_root)]
            if repetition % 2 == 0:
                variants.reverse()
            for variant, source_root in variants:
                used = sum(r["agent_calls"] for r in report["rows"])
                if used >= args.max_agent_calls:
                    report["stopped"] = "agent_budget"
                    save(output, report)
                    return 2
                row_path = workspace / f"{case['id']}-{repetition}-{variant}.json"
                command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--worker",
                           "--source-root", str(source_root), "--snapshot", str(snapshot_path),
                           "--case", case["id"], "--variant", variant, "--repeat", str(repetition),
                           "--max-agent-calls", str(min(8, args.max_agent_calls - used)), "--worker-output", str(row_path)]
                process = await asyncio.create_subprocess_exec(*command, cwd=ROOT, stdout=asyncio.subprocess.PIPE,
                                                               stderr=asyncio.subprocess.PIPE)
                async for line in process.stdout:
                    print(line.decode("utf-8").strip(), flush=True)
                await process.wait()
                if row_path.exists():
                    report["rows"].extend(json.loads(row_path.read_text(encoding="utf-8")))
                report["summary"] = aggregate(report["rows"])
                save(output, report)
                if process.returncode:
                    # 외부 SDK의 예외 본문이나 URL을 출력하지 않는다.
                    report["stopped"] = "worker_failed"
                    report["worker_exit_code"] = process.returncode
                    save(output, report)
                    return 2
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    return 0


async def main(args):
    os.environ["LANGSMITH_TRACING"] = "false"
    logging.basicConfig(level=logging.ERROR)
    return await worker(args) if args.worker else await controller(args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", default="bc828ce")
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--max-agent-calls", type=int, choices=range(1, 101), default=60)
    parser.add_argument("--output", default="docs/data/search-agent-before-after-2026-11-18.json")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source-root", help=argparse.SUPPRESS)
    parser.add_argument("--snapshot", help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", help=argparse.SUPPRESS)
    parser.add_argument("--case", help=argparse.SUPPRESS)
    parser.add_argument("--variant", help=argparse.SUPPRESS)
    parser.add_argument("--repeat", type=int, help=argparse.SUPPRESS)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
