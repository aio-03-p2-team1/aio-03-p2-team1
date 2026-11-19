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

from backend.agent.graph import GRAPH, REVIEW_GRAPH
from backend.normalization import criteria as crit
from backend.agent.search_cache import condition_key, review_cache_key
from backend.agent.embeddings import DIMENSIONS
from backend.agent.llm import INPUT_REVIEW_PROMPT_VERSION, PROMPT_VERSION
from backend.agent.radius import RADIUS_VERSION
from backend.agent.search_agent import AGENT_PROMPT_VERSION
from backend.errors import ApiError

RUN_FIELDS = (
    "run_id", "thread_id", "status", "end_reason", "partial", "criteria", "missing", "questions",
    "memory_used", "llm_features", "context_summary", "plan", "tool_calls", "candidates", "issues",
    "reflection_enabled", "reflection_count", "reflections", "retry_count", "scope", "error", "trace",
    "data_source",
    "ranking_method", "cache_key", "cache_hit", "snapshot_id", "radius",
    "confidence", "agent_request", "agent_decision", "photo_features", "input_review", "kind_check",
)
# 에이전트 요청은 대화(thread)마다 다르므로(이미 물은 것, '모르겠어요') 캐시에 넣지 않는다.
AGENT_FIELDS = ("agent_request", "agent_decision")
# 에이전트 적용 시 캐시는 검토 전 상태를 저장한다. 재정렬·반경 확대에 필요한 원본과 점수도 보관한다.
# 이 필드는 공개 run/저장 이력에는 넣지 않는다.
REVIEW_FIELDS = ("raw_items", "radius_items", "semantic_scores", "kind_labels", "total_count", "pages_fetched", "fetched_at", "search_query")


def agent_history(thread: dict[str, Any], declined: list[str] | None,
                  criteria: dict[str, Any] | None = None) -> dict[str, Any]:
    """같은 대화에서 이미 한 요청과 사용자가 '모르겠어요'한 항목을 모은다(반복 요청 방지).

    지난 검색이 범위·조건 변경을 물었고(questions) 이번 요청이 그 값을 바꿨으면 사용자가 동의한 것으로
    confirmed_fields 에 남긴다. 성별 조건 빼기에 동의(sex='any')하면 relaxed_fields 에 남겨, 같은 대화에서는
    설명에서 추출한 성별 특징도 쓰지 않는다.
    """
    history = dict(thread.get("agent") or {})
    history["declined"] = sorted(set(history.get("declined") or []) | set(declined or []))
    criteria = criteria or {}
    asked = {q.get("field") for q in thread.get("questions") or [] if isinstance(q, dict)}
    changed = {
        "radius": criteria.get("radius_step") not in (None, ""),
        "region": criteria.get("region") not in (None, "") and criteria.get("region") != (thread.get("criteria") or {}).get("region"),
        "sex": criteria.get("sex") == RELAX_VALUE,
    }
    confirmed = set(history.get("confirmed_fields") or []) | {f for f in asked if changed.get(f)}
    # 입력 검토의 글·사진 모순 질문은 대화의 첫 검색에서만 한다. 첫 검색에서 묻지 않고 찾았거나 이미 물었으면,
    # 넓히기·답하기처럼 같은 대화로 이어 찾을 때는 다시 묻지 않고 글을 기준으로 찾는다.
    history["review_asked"] = (bool(history.get("review_asked")) or "input_review" in asked
                               or bool(thread.get("last_run_id")))
    relaxed = set(history.get("relaxed_fields") or [])
    if criteria.get("sex") == RELAX_VALUE:
        relaxed.add("sex")
    elif criteria.get("sex"):
        relaxed.discard("sex")  # 사용자가 성별을 다시 고르면 그 값을 쓴다
    history["confirmed_fields"] = sorted(confirmed)
    history["relaxed_fields"] = sorted(relaxed)
    return history


RELAX_VALUE = "any"  # 화면이 '이 조건 빼고 찾기'에 동의했을 때 보내는 값(정규화에서 조건이 빠진다)


def review_memory(thread: dict[str, Any]) -> dict[str, Any] | None:
    """같은 대화의 직전 입력 검토 기억. LLM은 이전 호출을 기억하지 못하므로 서버가 대화 기록에서 꺼내 넘긴다.

    직전 검색이 모순을 물었고(questions 에 input_review) 이번 요청이 그 답이면, 물었던 항목을 사용자가 확정한 것으로 본다.
    """
    saved = thread.get("review")
    if not saved:
        return None
    confirmed = set(saved.get("confirmed_items") or [])
    asked = any(isinstance(q, dict) and q.get("field") == "input_review" for q in thread.get("questions") or [])
    if asked:
        confirmed |= {c.get("item") for c in saved.get("conflicts") or [] if c.get("item")}
    return {
        "organized_text": saved.get("organized_text") or "",
        "duplicates": list(saved.get("duplicates") or []),
        "conflicts": list(saved.get("conflicts") or []),
        "confirmed_items": sorted(confirmed),
    }


def saved_review(run: dict[str, Any], memory: dict[str, Any] | None) -> dict[str, Any] | None:
    """대화 기록에 남길 입력 검토 기억(정리한 글·보고한 중복·모순·확정 항목). 이번에 검토가 없으면 이전 기억을 유지한다."""
    review = run.get("input_review")
    if not review:
        return memory
    reported = list(dict.fromkeys([*((memory or {}).get("duplicates") or []), *(review.get("duplicates") or [])]))
    return {
        "organized_text": review.get("organized_text") or "",
        "duplicates": reported[:20],
        "conflicts": list(review.get("conflicts") or []),
        "confirmed_items": list((memory or {}).get("confirmed_items") or []),
    }


def next_history(history: dict[str, Any], request: dict[str, Any] | None) -> dict[str, Any]:
    history = {"photo_requests": history.get("photo_requests", 0), "info_requests": history.get("info_requests", 0),
               "asked_fields": list(history.get("asked_fields") or []), "declined": list(history.get("declined") or []),
               "confirmed_fields": list(history.get("confirmed_fields") or []),
               "relaxed_fields": list(history.get("relaxed_fields") or []),
               "review_asked": bool(history.get("review_asked"))}
    if request and request["type"] == "photo":
        history["photo_requests"] += 1
    elif request and request["type"] == "info":
        history["info_requests"] += 1
        history["asked_fields"].append(request["field"])
    return history


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_search(deps: dict[str, Any], owner: str, request: dict[str, Any]) -> dict[str, Any]:
    store = deps["store"]
    thread_id = request.get("thread_id") or uuid.uuid4().hex
    thread = await store.get(owner, "thread", thread_id) or {}
    session_criteria = thread.get("criteria")
    history = agent_history(thread, request.get("declined"), request.get("criteria"))
    memory = review_memory(thread)
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
        "agent_history": history,
        "photo_features": request.get("photo"),  # 서버가 보관한 사진 분석 결과(없으면 None)
        "review_memory": memory,  # 같은 대화의 직전 입력 검토 기억(없으면 None)
        "llm_features": {},
    }
    # 에이전트 루프(걸음 최대 4, 다시 찾기 최대 2)까지 들어가도 넉넉하게 잡는다.
    graph_deps = deps
    config = {"configurable": graph_deps, "recursion_limit": 80}
    cache = deps.get("search_cache")
    key = condition_key(owner, normalized, source=deps["animal"].source,
                        model={"embedding": getattr(deps.get("embedder"), "model", "sample"), "dimensions": DIMENSIONS,
                               "features": getattr(deps.get("llm"), "model", None),
                               # 입력 검토(글·사진 정리)를 쓰면 그 프롬프트 판이, 아니면 특징 추출 프롬프트 판이 결과를 정한다.
                               "feature_prompt": INPUT_REVIEW_PROMPT_VERSION if hasattr(deps.get("llm"), "review_input") else PROMPT_VERSION,
                               "review": AGENT_PROMPT_VERSION if graph_deps.get("search_agent") else None,
                               # 성별 조건 빼기에 동의한 대화는 설명의 성별 특징도 쓰지 않아 결과가 다르다.
                               "relaxed": history.get("relaxed_fields") or [],
                               # 반경 계산 방식과 지도 키 유무에 따라 결과가 달라지므로 캐시 키에 넣는다.
                               "radius": RADIUS_VERSION if getattr(deps.get("kakao"), "configured", False) else "off",
                               # 사진 특징이 다르면 결과가 달라지므로 캐시 키에 넣는다.
                               "photo": request.get("photo"),
                               # 같은 대화의 이전 검토 기억이 다르면 입력 검토 결과가 달라진다.
                               "review_memory": memory},
                        reflection=request.get("reflection_enabled", True))
    cache_hit = False

    async def execute(graph=GRAPH, initial=None, *, defer_agent=False):
        try:
            graph_config = {**config, "configurable": {
                **graph_deps, "_defer_agent": defer_agent and bool(graph_deps.get("search_agent")),
            }}
            # 조회와 검토를 합쳐 요청당 기존 120초 한도를 지킨다.
            remaining = max(0, 120 - (time.perf_counter() - started))
            return await asyncio.wait_for(graph.ainvoke(state if initial is None else initial, graph_config),
                                          timeout=remaining)
        except TimeoutError as exc:
            raise ApiError(504, "search_timeout", "검색 시간이 초과되었습니다. 조건을 좁혀 다시 시도해 주세요.") from exc

    def review_ready(result):
        return result.get("trace", [])[-1:] == ["validate"] and bool(graph_deps.get("search_agent"))

    if cache and not missing and not errors:
        result = await cache.get(key)
        if result is None:
            async with cache.lock(key):
                result = await cache.get(key)
                if result is None:
                    result = await execute(defer_agent=True)
                    result["snapshot_id"] = run_id
                    # LLM이 있으면 검토 전 원본을 저장한다. 대화별 요청·조건 수정 결과는 캐시하지 않는다.
                    ready = review_ready(result)
                    if not result.get("error") and (ready or result.get("status") == "completed"):
                        fields = (*RUN_FIELDS, *REVIEW_FIELDS) if ready else RUN_FIELDS
                        snapshot = {k: result.get(k) for k in fields
                                    if k not in ("run_id", "thread_id", "cache_key", "cache_hit", *AGENT_FIELDS)}
                        await cache.put(key, snapshot)
                else:
                    cache_hit = True
        else:
            cache_hit = True
    else:
        result = await execute()
    ready = review_ready(result)
    if cache_hit:
        result["context_summary"] = {**(result.get("context_summary") or {}), "origin": origins}
        result["memory_used"] = {k: normalized[k] for k, source in origins.items() if source == "memory" and k in normalized}
        # 캐시의 과거 호출·성찰은 이번 실행의 호출 수에 포함하지 않는다.
        result.update(tool_calls=[], reflection_count=0, reflections=[], retry_count=0, trace=["cache_hit"])
    review_cache_hit = False
    if ready:
        # 같은 조회 결과(캐시)에 같은 대화 맥락(이미 한 요청·거절·사진)이면 에이전트 판단도 같으므로
        # 검토 결과를 맥락별로 캐시해 LLM 을 다시 부르지 않는다. 맥락이 바뀌면(사진 요청 후 등) 키가 달라져 새로 판단한다.
        review_key = review_cache_key(key, history, state["photo_features"]) if cache else None
        reviewed = await cache.get(review_key) if cache_hit and review_key else None
        if reviewed is not None:
            result = {**result, **reviewed}
            decision = dict(result.get("agent_decision") or {})
            if decision:
                result["agent_decision"] = {**decision, "cached": True}
            result["trace"] = ["cache_hit", "review_cache_hit"]
            review_cache_hit = True
        else:
            # 잠금을 놓은 뒤 검토한다. 동일 조건도 매 대화의 입력·사진·거절·질문 이력으로 새로 판단한다.
            result = await execute(REVIEW_GRAPH, {**result, "run_id": run_id, "thread_id": thread_id,
                                                 "owner": owner, "request": state["request"],
                                                 "agent_history": history, "photo_features": state["photo_features"]})
            if review_key and not result.get("error") and result.get("status") in ("completed", "partial", "awaiting_input"):
                await cache.put(review_key, {k: result.get(k) for k in (*RUN_FIELDS, *AGENT_FIELDS)
                                             if k not in ("run_id", "thread_id", "cache_key", "cache_hit",
                                                          "tool_calls", "trace", "reflections", "reflection_count",
                                                          "retry_count", "context_summary", "memory_used")})
    run = {k: result.get(k) for k in RUN_FIELDS}
    run["run_id"] = run_id
    run["thread_id"] = thread_id
    run["cache_key"] = key if cache else None
    run["cache_hit"] = cache_hit
    run["review_cache_hit"] = review_cache_hit
    run["data_source"] = result.get("data_source") or deps["animal"].source
    run["created_at"] = _now()
    run["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    run["tool_call_count"] = len(run.get("tool_calls") or [])
    await store.put(owner, "run", run_id, run)
    # 같은 세션의 확인된 조건(사용자가 입력한 값만)과 미해결 질문을 저장한다.
    origin = (result.get("context_summary") or {}).get("origin") or {}
    confirmed = {
        k: v
        for k, v in normalized.items()
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
            "agent": next_history(history, run.get("agent_request")),
            "review": saved_review(run, memory),
            "updated_at": _now(),
        },
    )
    return run
