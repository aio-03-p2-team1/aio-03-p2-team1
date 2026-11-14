"""그래프 실행과 실행 이력·세션(thread) 저장.

- 단기 기억: thread 문서(같은 사용자·세션의 확인된 조건, 미해결 질문)
- 실행 이력: run 문서(조건·도구 호출·성찰 기록·후보·종료 상태)
- 체크포인트: 그래프는 한 요청 안에서 끝까지 실행되고, 추가 질문 상태는 thread 문서로
  영속하므로 서버가 재시작되어도 같은 thread_id 로 이어서 처리할 수 있다.
"""

from __future__ import annotations

import time
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.agent.graph import GRAPH
from backend.agent import criteria as crit
from backend.agent.search_cache import condition_key
from backend.agent.embeddings import DIMENSIONS
from backend.agent.llm import PROMPT_VERSION
from backend.agent.radius import RADIUS_VERSION
from backend.errors import ApiError

RUN_FIELDS = (
    "run_id", "thread_id", "status", "end_reason", "partial", "criteria", "missing", "questions",
    "memory_used", "llm_features", "context_summary", "plan", "tool_calls", "candidates", "issues",
    "reflection_enabled", "reflection_count", "reflections", "retry_count", "scope", "error", "trace",
    "data_source",
    "ranking_method", "cache_key", "cache_hit", "snapshot_id", "radius",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_search(deps: dict[str, Any], owner: str, request: dict[str, Any]) -> dict[str, Any]:
    store = deps["store"]
    thread_id = request.get("thread_id") or uuid.uuid4().hex
    thread = await store.get(owner, "thread", thread_id) or {}
    session_criteria = thread.get("criteria")
    profile = (await store.get(owner, "memory", request["profile_id"]) or {}) if request.get("profile_id") else None
    merged, origins = crit.merge_conditions(request.get("criteria", {}), session_criteria, (profile or {}).get("confirmed"))
    normalized, missing, errors = crit.normalize(merged)
    run_id = uuid.uuid4().hex
    started = time.perf_counter()
    state = {
        "run_id": run_id,
        "owner": owner,
        "thread_id": thread_id,
        "profile_id": request.get("profile_id") or None,
        "request": {**request.get("criteria", {}), "_session_criteria": session_criteria, "_profile_memory": profile},
        "reflection_enabled": bool(request.get("reflection_enabled", True)),
        "reflection_count": 0,
        "retry_count": 0,
        "tool_calls": [],
        "reflections": [],
        "trace": [],
    }
    config = {"configurable": deps, "recursion_limit": 40}
    cache = deps.get("search_cache")
    key = condition_key(owner, normalized, source=deps["animal"].source,
                        model={"embedding": getattr(deps.get("embedder"), "model", "sample"), "dimensions": DIMENSIONS,
                               "features": getattr(deps.get("llm"), "model", None), "feature_prompt": PROMPT_VERSION,
                               # 반경 계산 방식과 지도 키 유무에 따라 결과가 달라지므로 캐시 키에 넣는다.
                               "radius": RADIUS_VERSION if getattr(deps.get("kakao"), "configured", False) else "off"},
                        reflection=request.get("reflection_enabled", True))
    cache_hit = False

    async def execute():
        try:
            return await asyncio.wait_for(GRAPH.ainvoke(state, config), timeout=120)
        except TimeoutError as exc:
            raise ApiError(504, "search_timeout", "검색 시간이 초과되었습니다. 조건을 좁혀 다시 시도해 주세요.") from exc

    if cache and not missing and not errors:
        result = await cache.get(key)
        if result is None:
            async with cache.lock(key):
                result = await cache.get(key)
                if result is None:
                    result = await execute()
                    result["snapshot_id"] = run_id
                    if not result.get("error") and result.get("status") == "completed":
                        snapshot = {k: result.get(k) for k in RUN_FIELDS if k not in ("run_id", "thread_id", "cache_key", "cache_hit")}
                        await cache.put(key, snapshot)
                else:
                    cache_hit = True
        else:
            cache_hit = True
    else:
        result = await execute()
    if cache_hit:
        result["context_summary"] = {**(result.get("context_summary") or {}), "origin": origins}
        result["memory_used"] = {k: normalized[k] for k, source in origins.items() if source == "memory" and k in normalized}
    run = {k: result.get(k) for k in RUN_FIELDS}
    run["run_id"] = run_id
    run["thread_id"] = thread_id
    run["cache_key"] = key if cache else None
    run["cache_hit"] = cache_hit
    run["data_source"] = result.get("data_source") or deps["animal"].source
    run["created_at"] = _now()
    run["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    run["tool_call_count"] = len(run.get("tool_calls") or [])
    if cache_hit:
        run.update(tool_calls=[], tool_call_count=0, reflection_count=0, reflections=[], retry_count=0, trace=["cache_hit"])
    await store.put(owner, "run", run_id, run)
    # 같은 세션의 확인된 조건(사용자가 입력한 값만)과 미해결 질문을 저장한다.
    origin = (result.get("context_summary") or {}).get("origin") or {}
    confirmed = {
        k: v
        for k, v in (result.get("criteria") or {}).items()
        if k not in ("region_code", "region_name") and origin.get(k) != "memory"
    }
    await store.put(
        owner,
        "thread",
        thread_id,
        {
            "criteria": confirmed,
            "status": run["status"],
            "questions": run.get("questions") or [],
            "last_run_id": run_id,
            "updated_at": _now(),
        },
    )
    return run
