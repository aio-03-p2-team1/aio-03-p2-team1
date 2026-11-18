"""관리자 API (`/admin/*`). 모든 경로는 `require_admin`(계정 문서의 role=admin)만 통과한다.

- 현황: 에이전트·외부 연동 설정 상태, 저장소·Redis 연결 확인, 한도·프롬프트 버전
- 로그: 프로세스 메모리의 최근 로그(`backend/admin/audit_log.py`)
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
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from backend.admin import audit_log as admin_log
from backend.admin.service import (
    RUN_LIST_FIELDS,
    RUN_STAT_FIELDS,
    SCAN_LIMIT,
    _as_list,
    accounts as _accounts,
    agent_stats,
    check_id as _check_id,
    check_owner as _check_owner,
    clean_run,
    run_row as _run_row,
    who as _who,
)
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

def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
