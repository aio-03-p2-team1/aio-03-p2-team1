"""관리자 API (`/admin/*`). 모든 경로는 `require_admin`(계정 문서의 role=admin)만 통과한다.

- 현황: 에이전트·외부 연동 설정 상태, 저장소·Redis 연결 확인, 한도·프롬프트 버전
- 로그: 프로세스 메모리의 최근 로그(`backend/admin_log.py`)
- 실행 내역·에이전트 분석: 모든 사용자의 검색 실행(run) 문서를 후보 목록 없이 읽어 집계
- 관리: 사용자 정지/해제, 검색 내역·게시물·댓글·전단지 삭제

관리자도 비밀번호 해시·세션 토큰·전단지 사진 원본은 받지 않는다.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from backend import admin_log
from backend.agent import search_agent as agent_mod
from backend.agent.llm import PROMPT_VERSION
from backend.agent.radius import RADIUS_VERSION
from backend.auth.sessions import SessionUser
from backend.deps import ADMIN_ROLE, AppContext, get_ctx, require_admin
from backend.errors import ApiError
from backend.routers import comments as comments_mod
from backend.routers import posters as posters_mod
from backend.routers import posts as posts_mod

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("dasimanna.admin")
STARTED_AT = datetime.now(timezone.utc).isoformat()

OWNER = re.compile(r"^[0-9a-f]{64}$")  # 사용자 소유자 키(이메일 SHA-256)
DOC_ID = re.compile(r"^[0-9a-f]{32}$")
SCAN_LIMIT = 500  # 한 번에 읽는 최대 문서 수(관리자 화면용)

# 실행(run) 목록에서 읽는 필드. 후보(candidates, 최대 300건)·도구 호출 원문은 빼서 가볍게 읽는다.
RUN_LIST_FIELDS = (
    "run_id", "thread_id", "status", "end_reason", "partial", "criteria", "reflection_enabled", "reflection_count",
    "retry_count", "ranking_method", "cache_hit", "data_source", "created_at", "elapsed_ms", "tool_call_count",
    "confidence", "agent_request", "agent_decision", "error", "issues", "radius", "scope",
)
# 에이전트 분석(집계)에 쓰는 필드
RUN_STAT_FIELDS = (
    "status", "end_reason", "reflection_enabled", "reflection_count", "retry_count", "cache_hit", "elapsed_ms",
    "tool_calls", "confidence", "agent_decision", "agent_request", "issues", "reflections", "ranking_method",
    "error", "created_at",
)


# 운영 DB 에는 지금 코드와 형태가 다른 예전 실행 기록이 섞여 있다(예: tool_calls 가 목록이 아니라 숫자).
# 관리자 화면은 기록 하나 때문에 전체가 500 으로 깨지지 않도록, 읽을 때 형태를 맞추고 맞지 않는 값은 비운다.
_RUN_LISTS = ("tool_calls", "issues", "reflections", "trace", "questions")
_RUN_DICTS = ("criteria", "confidence", "agent_decision", "agent_request", "radius", "scope")
_RUN_NUMS = ("reflection_count", "retry_count", "tool_call_count", "elapsed_ms")


def _as_list(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def clean_run(run: Any) -> tuple[dict[str, Any], bool]:
    """실행 문서 → (형태를 맞춘 사본, 맞지 않는 값이 있었는지)."""
    if not isinstance(run, dict):
        return {}, True
    out = dict(run)
    odd = False
    for key in _RUN_LISTS:
        if key in out and out[key] is not None:
            cleaned = _as_list(out[key]) if key != "trace" else [v for v in out[key] if isinstance(v, str)] if isinstance(out[key], list) else []
            if key == "tool_calls" and isinstance(out[key], (int, float)) and not isinstance(out[key], bool):
                if out.get("tool_call_count") is None:  # 예전 기록: 호출 목록 대신 개수만 저장
                    out["tool_call_count"] = int(out[key])
            odd = odd or not isinstance(out[key], list) or len(cleaned) != len(out[key])
            out[key] = cleaned
    for key in _RUN_DICTS:
        if key in out and out[key] is not None and not isinstance(out[key], dict):
            odd = True
            out[key] = None
    if "error" in out and out["error"] is not None and not isinstance(out["error"], dict):
        odd = True
        out["error"] = {"code": str(out["error"])[:80]}
    for key in _RUN_NUMS:
        value = out.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            odd = True
            out[key] = None
    decision = out.get("agent_decision")
    if decision is not None:
        log_ = decision.get("log")
        if log_ is not None and not isinstance(log_, list):
            odd = True
        out["agent_decision"] = {**decision, "log": _as_list(log_)}
    conf = out.get("confidence")
    if conf is not None:
        reasons = conf.get("reasons")
        out["confidence"] = {**conf, "reasons": [r for r in reasons if isinstance(r, str)] if isinstance(reasons, list) else []}
    for key in ("status", "end_reason", "ranking_method", "data_source", "created_at"):
        if out.get(key) is not None and not isinstance(out[key], str):
            odd = True
            out[key] = str(out[key])
    return out, odd


def _check_owner(owner: str) -> None:
    if not OWNER.match(owner):
        raise ApiError(404, "not_found", "대상을 찾을 수 없습니다.")


def _check_id(doc_id: str) -> None:
    if not DOC_ID.match(doc_id):
        raise ApiError(404, "not_found", "대상을 찾을 수 없습니다.")


async def _accounts(ctx: AppContext) -> dict[str, dict[str, Any]]:
    """소유자 키 → {email, name}. 비밀번호 해시는 꺼내지 않는다."""
    rows = await ctx.store.list_kind("identity", SCAN_LIMIT)
    return {r["owner"]: {"email": r["data"].get("email"), "name": r["data"].get("name")} for r in rows}


def _who(accounts: dict[str, dict[str, Any]], owner: str | None) -> dict[str, Any]:
    acc = accounts.get(owner or "") or {}
    return {"owner": owner, "email": acc.get("email"), "name": acc.get("name")}


# ---------------------------------------------------------------- 현황


@router.get("/overview")
async def overview(_: SessionUser = Depends(require_admin), ctx: AppContext = Depends(get_ctx)):
    s = ctx.settings
    checks: dict[str, Any] = {}
    started = time.perf_counter()
    try:
        await ctx.store.get("health", "identity", "check")
        checks["store"] = {"ok": True, "ms": round((time.perf_counter() - started) * 1000)}
    except Exception as exc:  # 상태 화면은 실패도 보여 줘야 하므로 삼키고 코드만 남긴다
        checks["store"] = {"ok": False, "error": getattr(exc, "code", type(exc).__name__)}
    started = time.perf_counter()
    try:
        await ctx.sessions._redis.ping()
        checks["redis"] = {"ok": True, "ms": round((time.perf_counter() - started) * 1000)}
    except Exception as exc:
        checks["redis"] = {"ok": False, "error": type(exc).__name__}

    def on(value: Any) -> bool:
        return value is not None

    return {
        "started_at": STARTED_AT,
        "app_mode": s.app_mode,
        "storage_backend": s.storage_backend,
        "checks": checks,
        "integrations": {
            "animal_api": {"on": getattr(ctx.animal, "source", None) == "api", "source": getattr(ctx.animal, "source", None)},
            "lost_api": {"on": on(ctx.lost)},
            "kakao": {"on": bool(getattr(ctx.kakao, "configured", False))},
            "feature_llm": {"on": on(ctx.llm), "model": getattr(ctx.llm, "model", None)},
            "photo_llm": {"on": on(ctx.photo_llm), "model": getattr(ctx.photo_llm, "model", None)},
            "embedder": {"on": on(ctx.embedder), "model": getattr(ctx.embedder, "model", None)},
            "search_agent": {"on": on(ctx.search_agent), "model": getattr(ctx.search_agent, "model", None)},
            "search_cache": {"on": on(ctx.search_cache)},
            "langsmith": {"on": bool(s.langsmith_tracing and s.langsmith_api_key), "project": s.langsmith_project},
        },
        "versions": {
            "feature_prompt": PROMPT_VERSION,
            "agent_prompt": agent_mod.AGENT_PROMPT_VERSION,
            "radius": RADIUS_VERSION,
        },
        "limits": {
            "max_reflections": s.max_reflections,
            "max_tool_calls": s.max_tool_calls,
            "agent_max_steps": agent_mod.MAX_STEPS,
            "agent_max_reruns": agent_mod.MAX_RERUNS,
            "request_timeout_seconds": s.request_timeout_seconds,
        },
    }


# ---------------------------------------------------------------- 로그


@router.get("/logs")
async def logs(
    level: str | None = Query(default=None, pattern="^(INFO|WARNING|ERROR|CRITICAL)$"),
    source: str | None = Query(default=None, pattern="^(request|server)$"),
    limit: int = Query(default=200, ge=1, le=admin_log.MAX_ENTRIES),
    _: SessionUser = Depends(require_admin),
):
    items = admin_log.LOG_BUFFER.entries(level, source, limit)
    return {"items": items, "count": len(items), "capacity": admin_log.MAX_ENTRIES, "started_at": STARTED_AT}


# ---------------------------------------------------------------- 사용자


@router.get("/users")
async def users(_: SessionUser = Depends(require_admin), ctx: AppContext = Depends(get_ctx)):
    rows = await ctx.store.list_kind("identity", SCAN_LIMIT)
    runs = await ctx.store.list_kind("run", SCAN_LIMIT, fields=("created_at",))
    run_count = Counter(r["owner"] for r in runs)
    posts = await ctx.store.list_kind("post", SCAN_LIMIT, fields=("author",))
    post_count = Counter(r["data"].get("author") for r in posts)
    items = [{
        "owner": r["owner"],
        "email": r["data"].get("email"),
        "name": r["data"].get("name"),
        "role": r["data"].get("role") or "user",
        "disabled": bool(r["data"].get("disabled")),
        "created_at": r["data"].get("created_at"),
        "runs": run_count.get(r["owner"], 0),
        "posts": post_count.get(r["owner"], 0),
    } for r in rows]
    items.sort(key=lambda u: u["created_at"] or "", reverse=True)
    return {"items": items, "count": len(items), "scan_limit": SCAN_LIMIT}


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disabled: bool


@router.patch("/users/{owner}")
async def update_user(owner: str, body: UserPatch, admin: SessionUser = Depends(require_admin),
                      ctx: AppContext = Depends(get_ctx)):
    _check_owner(owner)
    account = await ctx.store.get(owner, "identity", "account")
    if not account:
        raise ApiError(404, "not_found", "사용자를 찾을 수 없습니다.")
    if owner == admin.owner or account.get("role") == ADMIN_ROLE:
        raise ApiError(422, "admin_protected", "관리자 계정은 정지할 수 없어요.")
    account["disabled"] = body.disabled
    await ctx.store.put(owner, "identity", "account", account)
    log.info("admin %s user owner=%s…", "disabled" if body.disabled else "enabled", owner[:8])
    return {"owner": owner, "disabled": body.disabled}


# ---------------------------------------------------------------- 실행 내역(검색 내역)


def _run_row(row: dict[str, Any], accounts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run, odd = clean_run(row["data"])
    decision = run.get("agent_decision") or {}
    conf = run.get("confidence") or {}
    return {
        **_who(accounts, row["owner"]),
        "id": row["id"],
        "status": run.get("status"),
        "end_reason": run.get("end_reason"),
        "criteria": run.get("criteria"),
        "reflection_enabled": run.get("reflection_enabled"),
        "reflection_count": run.get("reflection_count") or 0,
        "retry_count": run.get("retry_count") or 0,
        "tool_call_count": run.get("tool_call_count") or 0,
        "cache_hit": bool(run.get("cache_hit")),
        "elapsed_ms": run.get("elapsed_ms"),
        "data_source": run.get("data_source"),
        "ranking_method": run.get("ranking_method"),
        "confidence_low": bool(conf.get("low")),
        "confidence_reasons": conf.get("reasons") or [],
        "agent_source": decision.get("source"),
        "agent_final_tool": decision.get("final_tool"),
        "agent_steps": decision.get("steps") or 0,
        "agent_reruns": decision.get("reruns") or 0,
        "agent_request": (run.get("agent_request") or {}).get("type"),
        "issues": [i.get("type") for i in run.get("issues") or [] if isinstance(i, dict)],
        "error": (run.get("error") or {}).get("code"),
        "radius_km": (run.get("radius") or {}).get("km"),
        "created_at": run.get("created_at") or row.get("updated_at"),
        "malformed": odd,
    }


@router.get("/runs")
async def runs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=5000),
    _: SessionUser = Depends(require_admin),
    ctx: AppContext = Depends(get_ctx),
):
    rows = await ctx.store.list_kind("run", limit, offset, fields=RUN_LIST_FIELDS)
    accounts = await _accounts(ctx)
    items = [_run_row(r, accounts) for r in rows]
    return {"items": items, "count": len(items), "offset": offset, "limit": limit}


@router.get("/runs/{owner}/{run_id}")
async def run_detail(owner: str, run_id: str, _: SessionUser = Depends(require_admin), ctx: AppContext = Depends(get_ctx)):
    _check_owner(owner)
    _check_id(run_id)
    run = await ctx.store.get(owner, "run", run_id)
    if not run:
        raise ApiError(404, "run_not_found", "실행 기록을 찾을 수 없습니다.")
    raw_candidates = run.get("candidates")
    run, _ = clean_run(run)
    candidates = _as_list(raw_candidates)
    top = [{k: c.get(k) for k in ("id", "notice_no", "score", "lexical_score", "semantic_score", "rrf_ranks", "breed",
                                  "color", "sex", "happen_date", "happen_place", "distance_km", "evidence")}
           for c in candidates[:20]]
    accounts = await _accounts(ctx)
    return {**_who(accounts, owner), "run": {**{k: v for k, v in run.items() if k != "candidates"},
                                              "candidate_count": len(candidates), "top_candidates": top}}


@router.delete("/runs/{owner}/{run_id}", status_code=204)
async def delete_run(owner: str, run_id: str, _: SessionUser = Depends(require_admin), ctx: AppContext = Depends(get_ctx)):
    _check_owner(owner)
    _check_id(run_id)
    if not await ctx.store.delete(owner, "run", run_id):
        raise ApiError(404, "run_not_found", "실행 기록을 찾을 수 없습니다.")
    log.info("admin deleted run id=%s owner=%s…", run_id, owner[:8])


# ---------------------------------------------------------------- 에이전트 분석


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 2) if values else None


def _group_stats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """성찰 켬/끔 비교에 쓰는 실행 묶음 요약(보고서 지표의 원자료)."""
    n = len(runs)
    done = sum(1 for r in runs if r.get("status") in ("completed", "partial"))
    return {
        "runs": n,
        "completed_rate": _rate(done, n),
        "failed_rate": _rate(sum(1 for r in runs if r.get("status") == "failed"), n),
        "awaiting_input_rate": _rate(sum(1 for r in runs if r.get("status") == "awaiting_input"), n),
        "avg_reflection_count": _avg([r.get("reflection_count") or 0 for r in runs]),
        "avg_retry_count": _avg([r.get("retry_count") or 0 for r in runs]),
        "avg_tool_calls": _avg([len(r.get("tool_calls") or []) or r.get("tool_call_count") or 0 for r in runs]),
    }


def agent_stats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """실행 문서 목록 → 에이전트 정확도 개선용 집계. 캐시 적중 실행은 그래프를 돌지 않았으므로 도구·성찰 집계에서 뺀다."""
    runs = [clean_run(r)[0] for r in runs]
    total = len(runs)
    executed = [r for r in runs if not r.get("cache_hit")]
    tool_use: Counter = Counter()
    tool_fail: Counter = Counter()
    for r in executed:
        for call in r.get("tool_calls") or []:
            name = call.get("tool") or "?"
            tool_use[name] += 1
            if call.get("outcome") not in ("ok", "hit", "cached", None):
                tool_fail[name] += 1
    agent_runs = [r for r in executed if r.get("agent_decision")]
    agent_tool: Counter = Counter()
    agent_rejected: Counter = Counter()
    rejected_examples: list[dict[str, Any]] = []
    for r in agent_runs:
        for step in (r["agent_decision"].get("log") or []):
            if not step.get("tool"):
                continue
            agent_tool[step["tool"]] += 1
            if step.get("ok") is False:
                agent_rejected[step["tool"]] += 1
                if len(rejected_examples) < 20:
                    rejected_examples.append({"tool": step["tool"], "args": step.get("args"),
                                              "reason": step.get("rejected"), "at": r.get("created_at")})
    low = [r for r in executed if (r.get("confidence") or {}).get("low")]
    with_reflection = [r for r in executed if r.get("reflection_enabled") is not False]
    without_reflection = [r for r in executed if r.get("reflection_enabled") is False]
    return {
        "total_runs": total,
        "executed_runs": len(executed),
        "cache_hit_rate": _rate(total - len(executed), total),
        "status": dict(Counter(r.get("status") or "unknown" for r in runs)),
        "end_reason": dict(Counter(r.get("end_reason") or "-" for r in runs)),
        "errors": dict(Counter((r.get("error") or {}).get("code") for r in runs if r.get("error"))),
        "avg_elapsed_ms": _avg([r["elapsed_ms"] for r in executed if isinstance(r.get("elapsed_ms"), (int, float))]),
        "issues": dict(Counter(i.get("type") for r in executed for i in r.get("issues") or [] if isinstance(i, dict))),
        "reflections": dict(Counter(x.get("type") or x.get("issue") for r in executed for x in r.get("reflections") or []
                                    if isinstance(x, dict))),
        "tool_use": dict(tool_use.most_common()),
        "tool_fail": dict(tool_fail.most_common()),
        "confidence": {
            "low_rate": _rate(len(low), len(executed)),
            "reasons": dict(Counter(reason for r in low for reason in (r["confidence"].get("reasons") or []))),
        },
        "agent": {
            "runs": len(agent_runs),
            "source": dict(Counter(r["agent_decision"].get("source") or "-" for r in agent_runs)),
            "final_tool": dict(Counter(r["agent_decision"].get("final_tool") or "-" for r in agent_runs)),
            "tool_calls": dict(agent_tool.most_common()),
            "rejected": dict(agent_rejected.most_common()),
            "avg_steps": _avg([r["agent_decision"].get("steps") or 0 for r in agent_runs]),
            "avg_reruns": _avg([r["agent_decision"].get("reruns") or 0 for r in agent_runs]),
            "requests": dict(Counter((r.get("agent_request") or {}).get("type") for r in agent_runs if r.get("agent_request"))),
            "rejected_examples": rejected_examples,
        },
        "reflection_compare": {"on": _group_stats(with_reflection), "off": _group_stats(without_reflection)},
    }


@router.get("/agent/stats")
async def stats(
    limit: int = Query(default=300, ge=1, le=SCAN_LIMIT),
    _: SessionUser = Depends(require_admin),
    ctx: AppContext = Depends(get_ctx),
):
    rows = await ctx.store.list_kind("run", limit, fields=RUN_STAT_FIELDS)
    cleaned = [clean_run(r["data"]) for r in rows]
    runs = [run for run, _ in cleaned]
    return {"scanned": len(runs), "limit": limit, "malformed_runs": sum(1 for _, odd in cleaned if odd), **agent_stats(runs)}


# ---------------------------------------------------------------- 게시물


@router.get("/posts")
async def posts(_: SessionUser = Depends(require_admin), ctx: AppContext = Depends(get_ctx)):
    rows = await ctx.store.list_kind(posts_mod.KIND, SCAN_LIMIT)
    accounts = await _accounts(ctx)
    items = [{
        "id": r["id"],
        "pet_name": r["data"].get("pet_name"),
        "species": r["data"].get("species"),
        "breed": r["data"].get("breed"),
        "region": r["data"].get("region"),
        "lost_date": r["data"].get("lost_date"),
        "has_photo": bool(r["data"].get("photo")),
        "voices": len(r["data"].get("voices") or []),
        "author": _who(accounts, r["data"].get("author")),
        "created_at": r["data"].get("created_at"),
    } for r in rows if r["owner"] == posts_mod.BOARD_OWNER]
    return {"items": items, "count": len(items)}


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: str, _: SessionUser = Depends(require_admin), ctx: AppContext = Depends(get_ctx)):
    _check_id(post_id)
    data = await ctx.store.get(posts_mod.BOARD_OWNER, posts_mod.KIND, post_id)
    if not data:
        raise ApiError(404, "post_not_found", "게시글을 찾을 수 없습니다.")
    await ctx.store.delete(posts_mod.BOARD_OWNER, posts_mod.KIND, post_id)
    for voice in data.get("voices", []):
        await ctx.post_audio.delete(voice["key"])
    await comments_mod.delete_all_comments(ctx, post_id)
    log.info("admin deleted post id=%s", post_id)


# ---------------------------------------------------------------- 댓글


@router.get("/comments")
async def comments(_: SessionUser = Depends(require_admin), ctx: AppContext = Depends(get_ctx)):
    rows = await ctx.store.list_kind(comments_mod.KIND, SCAN_LIMIT)
    accounts = await _accounts(ctx)
    prefix = comments_mod.comment_owner("")
    items = [{
        "id": r["id"],
        "post_id": r["owner"][len(prefix):],
        "body": r["data"].get("body"),
        "author": _who(accounts, r["data"].get("author")),
        "target_source": r["data"].get("target_source"),
        "created_at": r["data"].get("created_at"),
    } for r in rows if r["owner"].startswith(prefix)]
    return {"items": items, "count": len(items)}


@router.delete("/comments/{post_id}/{comment_id}", status_code=204)
async def delete_comment(post_id: str, comment_id: str, _: SessionUser = Depends(require_admin),
                         ctx: AppContext = Depends(get_ctx)):
    _check_id(comment_id)
    if not re.fullmatch(r"[0-9a-z-]{1,80}", post_id):
        raise ApiError(404, "comment_not_found", "댓글을 찾을 수 없습니다.")
    if not await ctx.store.delete(comments_mod.comment_owner(post_id), comments_mod.KIND, comment_id):
        raise ApiError(404, "comment_not_found", "댓글을 찾을 수 없습니다.")
    log.info("admin deleted comment id=%s post=%s", comment_id, post_id)


# ---------------------------------------------------------------- 전단지


@router.get("/posters")
async def posters(_: SessionUser = Depends(require_admin), ctx: AppContext = Depends(get_ctx)):
    rows = await ctx.store.list_kind("poster", SCAN_LIMIT)
    accounts = await _accounts(ctx)
    items = [{**posters_mod._summary(r["id"], r["data"], r.get("updated_at")), "author": _who(accounts, r["owner"])}
             for r in rows]
    return {"items": items, "count": len(items)}


@router.get("/posters/{owner}/{poster_id}")
async def poster_detail(owner: str, poster_id: str, _: SessionUser = Depends(require_admin),
                        ctx: AppContext = Depends(get_ctx)):
    _check_owner(owner)
    _check_id(poster_id)
    doc = await ctx.store.get(owner, "poster", poster_id)
    if not doc:
        raise ApiError(404, "poster_not_found", "전단지를 찾을 수 없습니다.")
    return {"id": poster_id, **doc}


@router.delete("/posters/{owner}/{poster_id}", status_code=204)
async def delete_poster(owner: str, poster_id: str, _: SessionUser = Depends(require_admin),
                        ctx: AppContext = Depends(get_ctx)):
    _check_owner(owner)
    _check_id(poster_id)
    if not await ctx.store.delete(owner, "poster", poster_id):
        raise ApiError(404, "poster_not_found", "전단지를 찾을 수 없습니다.")
    log.info("admin deleted poster id=%s owner=%s…", poster_id, owner[:8])
