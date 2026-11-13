from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone
from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agent import criteria as crit
from backend.agent.llm import LlmError
from backend.agent.ranking import TOP_K, cosine, feature_text, fuse_rrf, in_scope, rank
from backend.agent.state import SearchState
from backend.tools.animal_api import AnimalApiError, short_region_name
from backend.tools.kakao import KakaoError

ROWS_PER_PAGE = 1000
LOCATE_TOP = 3
RETRY_BACKOFF_SECONDS = (0.5, 1.0)

ERROR_MESSAGES = {
    "animal_auth": "구조동물 API 인증에 실패했습니다. 서버의 ANIMAL_API_KEY 를 확인해야 합니다.",
    "animal_rate_limit": "구조동물 API 호출 한도를 넘었습니다. 잠시 후 다시 시도해 주세요.",
    "animal_timeout": "구조동물 API 응답 시간이 초과되었습니다.",
    "animal_network": "구조동물 API 에 연결하지 못했습니다.",
    "animal_upstream": "구조동물 API 서버 오류입니다.",
    "animal_response": "구조동물 API 응답 형식이 예상과 다릅니다.",
    "llm_auth": "OpenAI 인증 실패: OPENAI_API_KEY 교체 후 재배포가 필요합니다.",
    "llm_permission": "OpenAI 권한 부족: 프로젝트·키의 모델 권한을 확인해야 합니다.",
    "llm_model": "OpenAI 모델을 찾을 수 없습니다: 모델 이름과 접근 권한을 확인해야 합니다.",
    "llm_quota": "OpenAI 사용 한도·크레딧을 확인해야 합니다.",
    "llm_rate_limit": "OpenAI 호출 제한에 걸렸습니다. 잠시 후 다시 시도해 주세요.",
    "llm_timeout": "OpenAI 응답 시간이 초과되었습니다.",
    "llm_network": "OpenAI 에 연결하지 못했습니다.",
    "llm_request": "OpenAI 요청 설정 오류입니다.",
    "llm_upstream": "OpenAI 서버 오류입니다.",
    "llm_response": "OpenAI 응답 형식이 올바르지 않습니다.",
    "embedding_not_configured": "검색 임베딩 설정이 없습니다. OPENAI_API_KEY 설정이 필요합니다.",
    "unknown_region": "지원하지 않는 지역입니다.",
    "tool_budget": "도구 호출 한도에 도달해 검색을 멈췄습니다.",
}


def _deps(config) -> dict[str, Any]:
    return config["configurable"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _call(tool: str, args: dict[str, Any], outcome: str, reason: str, **extra) -> dict[str, Any]:
    return {"tool": tool, "args": args, "outcome": outcome, "reason": reason, "at": _now(), **extra}


async def analyze(state: SearchState, config) -> dict:
    session = (state.get("request") or {}).get("_session_criteria")
    merged, origin = crit.merge_conditions(state.get("request") or {}, session, None)
    criteria, missing, errors = crit.normalize(merged)
    return {
        "criteria": criteria,
        "missing": missing,
        "input_errors": errors,
        "questions": crit.questions_for(missing, errors),
        "context_summary": {"origin": origin},
        "trace": ["analyze"],
    }


def route_after_analyze(state: SearchState) -> str:
    return "ask" if state.get("missing") or state.get("input_errors") else "context"


async def ask(state: SearchState, config) -> dict:
    update: dict[str, Any] = {"status": "awaiting_input", "end_reason": "need_user_input", "trace": ["ask"]}
    if state.get("raw_items") is not None and state.get("fetched_at"):
        criteria = state.get("criteria") or {}
        update["scope"] = {
            "region": criteria.get("region_name") or criteria.get("region"),
            "species": criteria.get("species"),
            "start_date": criteria.get("start_date"),
            "end_date": criteria.get("end_date"),
            "total_count": state.get("total_count", 0),
            "fetched_at": state.get("fetched_at"),
            "data_source": state.get("data_source"),
        }
    return update


async def context(state: SearchState, config) -> dict:
    deps = _deps(config)
    criteria = dict(state["criteria"])
    origin = dict((state.get("context_summary") or {}).get("origin") or {})
    memory_used: dict[str, Any] = {}
    profile_id = state.get("profile_id")
    if profile_id:
        memory = (state.get("request") or {}).get("_profile_memory")
        if memory is None:
            memory = await deps["store"].get(state["owner"], "memory", profile_id)
        confirmed = (memory or {}).get("confirmed") or {}
        for key in crit.OPTIONAL_FIELDS:
            if not criteria.get(key) and confirmed.get(key):
                criteria[key] = str(confirmed[key])[:500]
                origin[key] = "memory"
                memory_used[key] = confirmed[key]
    update: dict[str, Any] = {
        "criteria": criteria,
        "memory_used": memory_used,
        "context_summary": {
            "origin": origin,
            # 모델 입력에는 서술·특징만 넣는다(이메일·연락처·키 제외).
            "llm_input_fields": ["description"] if criteria.get("description") else [],
        },
        "trace": ["context"],
    }
    llm = deps.get("llm")
    if llm and criteria.get("description"):
        started = time.perf_counter()
        try:
            features = await llm.extract(criteria["description"])
        except LlmError as exc:
            update["error"] = {"code": exc.code, "message": ERROR_MESSAGES.get(exc.code, exc.code)}
            update["tool_calls"] = [_call("llm_feature_extract", {"model": llm.model}, exc.code, "자유 서술에서 특징 추출")]
            return update
        update["llm_features"] = features.model_dump()
        update["tool_calls"] = [
            _call(
                "llm_feature_extract",
                {"model": llm.model},
                "ok",
                "자유 서술에서 특징 추출",
                ms=round((time.perf_counter() - started) * 1000),
            )
        ]
    return update


def route_after_context(state: SearchState) -> str:
    return "finalize" if state.get("error") else "plan"


def _match_region(name: str, regions, *, lenient: bool) -> Any:
    for r in regions:
        if r.name == name:
            return r
    if lenient:
        # 성찰 수정: '서울', '서울시', '경남' 같은 약칭을 공식 시도 이름으로 다시 매핑한다.
        wanted = short_region_name(name.strip())
        for r in regions:
            if short_region_name(r.name) == wanted:
                return r
    return None


async def plan(state: SearchState, config) -> dict:
    deps = _deps(config)
    criteria = dict(state["criteria"])
    steps: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    if criteria["region"] != "all" and not criteria.get("region_code"):
        regions = await deps["animal"].regions()
        calls.append(_call("animal_regions", {}, "ok", "지역 이름을 공식 시도 코드로 바꾸기 위해 조회"))
        lenient = bool((state.get("pending_fix") or {}).get("lenient_region"))
        match = _match_region(criteria["region"], regions, lenient=lenient)
        if match:
            criteria["region_code"] = match.code
            criteria["region_name"] = match.name
        else:
            issues.append({"type": "arg_mapping", "field": "region", "value": criteria["region"], "lenient": lenient})
    steps.append(
        {
            "tool": "animal_search",
            "why": "지역·기간·종류 조건으로 실제 공고를 조회",
            "max_pages": 1,
        }
    )
    return {
        "criteria": criteria,
        "plan": steps,
        "tool_calls": calls,
        "issues": issues,
        "pending_fix": None,
        "trace": ["plan"],
    }


def route_after_plan(state: SearchState) -> str:
    return "validate" if state.get("issues") else "execute"


async def execute(state: SearchState, config) -> dict:
    deps = _deps(config)
    settings = deps["settings"]
    animal = deps["animal"]
    criteria = state["criteria"]
    sleep = deps.get("sleep", asyncio.sleep)
    budget = settings.max_tool_calls - len(state.get("tool_calls") or [])
    calls: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    retries = state.get("retry_count", 0)
    total = 0
    page = 1
    fetched_at = None
    error = None
    args_base = {
        "region_code": criteria.get("region_code"),
        "start": criteria["start_date"],
        "end": criteria["end_date"],
        "species": criteria["species"],
    }
    while page <= 1:
        attempt = 0
        while True:
            if len(calls) >= budget:
                error = {"code": "tool_budget", "message": ERROR_MESSAGES["tool_budget"]}
                break
            args = {**args_base, "page": page, "rows": ROWS_PER_PAGE}
            try:
                result = await animal.search(
                    region_code=args["region_code"],
                    start=date.fromisoformat(args["start"]),
                    end=date.fromisoformat(args["end"]),
                    species=args["species"],
                    page=page,
                    rows=ROWS_PER_PAGE,
                )
            except AnimalApiError as exc:
                calls.append(_call("animal_search", args, exc.code, "공고 조회", attempt=attempt))
                if exc.retryable and attempt < len(RETRY_BACKOFF_SECONDS):
                    await sleep(RETRY_BACKOFF_SECONDS[attempt])
                    attempt += 1
                    retries += 1
                    continue
                error = {"code": exc.code, "message": ERROR_MESSAGES.get(exc.code, exc.code), "page": page}
                break
            calls.append(_call("animal_search", args, "ok", "공고 조회", count=len(result.items), attempt=attempt))
            items.extend(result.items[:ROWS_PER_PAGE])
            total = result.total_count
            fetched_at = result.fetched_at
            break
        if error:
            break
        break  # 요청당 원본 API 1페이지(최대 1,000건)만 조회한다.
    pages_fetched = page if not error else page - 1
    return {
        "raw_items": items,
        "total_count": total,
        "pages_fetched": max(pages_fetched, 0),
        "fetched_at": fetched_at or _now(),
        "data_source": animal.source,
        "retry_count": retries,
        "tool_calls": calls,
        "error": error,
        "pending_fix": None,
        "trace": ["execute"],
    }


async def rank_node(state: SearchState, config) -> dict:
    fix = state.get("pending_fix") or {}
    items = state.get("raw_items") or []
    if fix.get("dedupe"):
        seen: set[str] = set()
        unique = []
        for item in items:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            unique.append(item)
        items = unique
    candidates = rank(items, state["criteria"], state.get("llm_features"))
    deps = _deps(config)
    embedder = deps.get("embedder")
    scores = state.get("semantic_scores")
    calls = []
    if items and not state.get("error"):
        try:
            if not embedder and deps["animal"].source != "sample":
                raise LlmError("embedding_not_configured")
            if embedder:
                if scores is None:
                    vectors = await embedder.embed([feature_text(state["criteria"])] + [feature_text(item) for item in items])
                    if len(vectors) != len(items) + 1:
                        raise LlmError("llm_response")
                    scores = {item["id"]: cosine(vectors[0], vector) for item, vector in zip(items, vectors[1:])}
                    calls = [_call("embedding_search", {"model": embedder.model, "documents": len(items)}, "ok", "전체 공고와 검색 조건 임베딩")]
                candidates = fuse_rrf(candidates, scores)
        except (LlmError, ValueError) as exc:
            code = exc.code if isinstance(exc, LlmError) else "llm_response"
            return {"candidates": [], "error": {"code": code, "message": ERROR_MESSAGES.get(code, code)}, "trace": ["rank"]}
    return {"candidates": candidates, "semantic_scores": scores, "ranking_method": "rrf" if embedder else "sample_lexical",
            "tool_calls": calls, "pending_fix": None, "trace": ["rank"]}


async def validate(state: SearchState, config) -> dict:
    criteria = state["criteria"]

    carried = [i for i in (state.get("issues") or []) if i["type"] == "arg_mapping"]
    if carried:
        return {"issues": carried, "trace": ["validate"]}
    issues: list[dict[str, Any]] = []
    if state.get("error"):
        code = state["error"]["code"]
        issues.append({"type": "tool_error", "code": code, "fixable": False})
        return {"issues": issues, "trace": ["validate"]}
    candidates = state.get("candidates") or []
    ids = [c["id"] for c in candidates]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        issues.append({"type": "duplicates", "ids": dupes[:10], "count": len(dupes)})
    violations = [c["id"] for c in candidates if in_scope(c, criteria)]
    if violations:
        issues.append({"type": "condition_violation", "ids": violations[:10]})
    missing_id = [c for c in candidates if not c.get("id")]
    if missing_id:
        issues.append({"type": "field_missing", "field": "desertionNo", "count": len(missing_id)})
    if not candidates and state.get("raw_items") is not None and criteria.get("region") not in (None, "all") and "region_code" in criteria:
        issues.append({"type": "empty_narrow", "field": "region"})
    return {"issues": issues, "trace": ["validate"]}

FIXES = {
    "duplicates": {"strategy": "dedupe_and_rerank", "next": "rank", "fix": {"dedupe": True}},
    "condition_violation": {"strategy": "refilter_and_rerank", "next": "rank", "fix": {}},
    "arg_mapping": {"strategy": "remap_official_code", "next": "plan", "fix": {"lenient_region": True}},
    "empty_narrow": {"strategy": "ask_user_to_widen", "next": "ask", "fix": {}},
}


def route_after_validate(state: SearchState, config) -> str:
    issues = [i for i in state.get("issues") or [] if i["type"] in FIXES]
    if not issues:
        return "locate" if not state.get("error") and state.get("candidates") is not None else "finalize"
    if not state.get("reflection_enabled", True):
        return "finalize"
    if state.get("reflection_count", 0) >= _deps(config)["settings"].max_reflections:
        return "finalize"
    return "reflect"


async def reflect(state: SearchState, config) -> dict:
    issue = next(i for i in state["issues"] if i["type"] in FIXES)
    fix = FIXES[issue["type"]]
    record = {
        "round": state.get("reflection_count", 0) + 1,
        "issue": issue["type"],
        "evidence": {k: v for k, v in issue.items() if k != "type"},
        "strategy": fix["strategy"],
        "next": fix["next"],
        "at": _now(),
    }
    update: dict[str, Any] = {
        "reflection_count": state.get("reflection_count", 0) + 1,
        "reflections": [record],
        "pending_fix": {**fix["fix"], "next": fix["next"]},
        "issues": [],
        "trace": ["reflect"],
    }
    if issue["type"] == "empty_narrow":
        update["questions"] = [
            {
                "field": "region",
                "message": f"{state['criteria'].get('region_name') or state['criteria']['region']} 지역에서는 조건에 맞는 공고가 없었습니다. "
                "구조 지역은 실종 지역과 다를 수 있어요. 지역을 넓혀 '전체'로 다시 찾아볼까요?",
            }
        ]
    if issue["type"] == "arg_mapping" and issue.get("lenient"):
        # 공식 코드 재매핑까지 실패: 조건을 임의로 바꾸지 않고 사용자에게 묻는다.
        record["strategy"] = "ask_user_region"
        record["next"] = "ask"
        update["reflections"] = [record]
        update["pending_fix"] = {"next": "ask"}
        update["questions"] = [
            {"field": "region", "message": f"'{issue['value']}' 지역을 찾지 못했습니다. 시·도 이름(예: 서울, 경기)으로 다시 알려 주세요."}
        ]
    return update


def route_after_reflect(state: SearchState) -> str:
    return (state.get("pending_fix") or {}).get("next", "finalize")


async def locate(state: SearchState, config) -> dict:
    """상위 3개 후보만 보호센터 좌표를 조회한다(7장). 실패는 캐시하지 않는다."""
    deps = _deps(config)
    kakao = deps["kakao"]
    candidates = [dict(c) for c in state.get("candidates") or []]
    calls = []
    for c in candidates[:LOCATE_TOP]:
        if c.get("source") == "sample":
            c["location"] = {"status": "unavailable", "reason": "sample"}
            continue
        address = (c.get("care") or {}).get("address")
        if not kakao.configured or not address:
            c["location"] = {"status": "unavailable", "reason": "not_configured" if address else "address_missing"}
            continue
        try:
            result = await kakao.geocode(address)
        except KakaoError as exc:
            calls.append(_call("kakao_geocode", {"candidate": c["id"]}, exc.code, "상위 후보 보호센터 위치"))
            c["location"] = {"status": "error", "reason": exc.code}
            continue
        calls.append(_call("kakao_geocode", {"candidate": c["id"]}, result["status"], "상위 후보 보호센터 위치"))
        c["location"] = result
    return {"candidates": candidates, "tool_calls": calls, "trace": ["locate"]}


async def finalize(state: SearchState, config) -> dict:
    criteria = state.get("criteria") or {}
    error = state.get("error")
    issues = state.get("issues") or []
    candidates = (state.get("candidates") or [])[:TOP_K]
    total = state.get("total_count", 0)
    pages = state.get("pages_fetched", 0)
    fetched_rows = len(state.get("raw_items") or [])
    complete_scope = not error and fetched_rows >= total
    scope = {
        "region": criteria.get("region_name") or criteria.get("region"),
        "species": criteria.get("species"),
        "start_date": criteria.get("start_date"),
        "end_date": criteria.get("end_date"),
        "pages_fetched": pages,
        "total_count": total,
        "fetched_rows": fetched_rows,
        "complete": complete_scope,
        "fetched_at": state.get("fetched_at"),
        "data_source": state.get("data_source"),
    }
    unresolved = [i for i in issues if i["type"] in FIXES or i["type"] == "tool_error"]
    if any(i["type"] == "arg_mapping" for i in unresolved):
        error = error or {"code": "unknown_region", "message": ERROR_MESSAGES["unknown_region"]}
    if error and not candidates:
        status, reason = "failed", error["code"]
    elif error:
        status, reason = "partial", error["code"]
    elif unresolved:
        status, reason = "partial", "unresolved_issues"
    else:
        status, reason = "completed", "ok" if candidates else "empty_result"
    return {
        "candidates": candidates,
        "scope": scope,
        "status": status,
        "end_reason": reason,
        "partial": status == "partial" or not complete_scope,
        "error": error,
        "issues": unresolved,
        "trace": ["finalize"],
    }


def build_graph():
    g = StateGraph(SearchState)
    g.add_node("analyze", analyze)
    g.add_node("ask", ask)
    g.add_node("context", context)
    g.add_node("plan", plan)
    g.add_node("execute", execute)
    g.add_node("rank", rank_node)
    g.add_node("validate", validate)
    g.add_node("reflect", reflect)
    g.add_node("locate", locate)
    g.add_node("finalize", finalize)

    g.add_edge(START, "analyze")
    g.add_conditional_edges("analyze", route_after_analyze, {"ask": "ask", "context": "context"})
    g.add_edge("ask", END)
    g.add_conditional_edges("context", route_after_context, {"plan": "plan", "finalize": "finalize"})
    g.add_conditional_edges("plan", route_after_plan, {"validate": "validate", "execute": "execute"})
    g.add_edge("execute", "rank")
    g.add_edge("rank", "validate")
    g.add_conditional_edges(
        "validate",
        route_after_validate,
        {"reflect": "reflect", "locate": "locate", "finalize": "finalize"},
    )
    g.add_conditional_edges(
        "reflect",
        route_after_reflect,
        {"execute": "execute", "rank": "rank", "plan": "plan", "ask": "ask", "finalize": "finalize"},
    )
    g.add_edge("locate", "finalize")
    g.add_edge("finalize", END)
    return g.compile()

GRAPH = build_graph()
