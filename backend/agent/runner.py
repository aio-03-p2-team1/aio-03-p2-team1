"""그래프 실행과 실행 이력·세션(thread) 저장.

- 단기 기억: thread 문서(같은 사용자·세션의 확인된 조건, 미해결 질문)
- 실행 이력: run 문서(조건·도구 호출·성찰 기록·후보·종료 상태)
- 체크포인트: 그래프는 한 요청 안에서 끝까지 실행되고, 추가 질문 상태는 thread 문서로
  영속하므로 서버가 재시작되어도 같은 thread_id 로 이어서 처리할 수 있다.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.agent.graph import GRAPH

RUN_FIELDS = (
    "run_id", "thread_id", "status", "end_reason", "partial", "criteria", "missing", "questions",
    "memory_used", "llm_features", "context_summary", "plan", "tool_calls", "candidates", "issues",
    "reflection_enabled", "reflection_count", "reflections", "retry_count", "scope", "error", "trace",
    "data_source",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_search(deps: dict[str, Any], owner: str, request: dict[str, Any]) -> dict[str, Any]:
    store = deps["store"]
    thread_id = request.get("thread_id") or uuid.uuid4().hex
    thread = await store.get(owner, "thread", thread_id) or {}
    session_criteria = thread.get("criteria")
    run_id = uuid.uuid4().hex
    started = time.perf_counter()
    state = {
        "run_id": run_id,
        "owner": owner,
        "thread_id": thread_id,
        "profile_id": request.get("profile_id") or None,
        "request": {**request.get("criteria", {}), "_session_criteria": session_criteria},
        "reflection_enabled": bool(request.get("reflection_enabled", True)),
        "reflection_count": 0,
        "retry_count": 0,
        "tool_calls": [],
        "reflections": [],
        "trace": [],
    }
    config = {"configurable": deps, "recursion_limit": 40}
    result = await GRAPH.ainvoke(state, config)
    run = {k: result.get(k) for k in RUN_FIELDS}
    run["run_id"] = run_id
    run["thread_id"] = thread_id
    run["data_source"] = result.get("data_source") or deps["animal"].source
    run["created_at"] = _now()
    run["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    run["tool_call_count"] = len(run.get("tool_calls") or [])
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
