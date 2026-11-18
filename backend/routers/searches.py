from __future__ import annotations

import base64
import secrets
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.agent.llm import LlmError
from backend.agent import photo_store
from backend.agent import refinement_store
from backend.agent.photo import InvalidPhoto, decode_and_validate, shrink_for_analysis
from backend.tools import remote_photo
from backend.agent.runner import run_search
from backend.schemas.api import (PhotoAnalysisBody, PhotoAnalysisResponse, RefineDescriptionBody,
                                 RefineDescriptionResponse, SearchBody)
from backend.auth.sessions import AuthUnavailable, SessionUser
from backend.deps import AppContext, current_user, get_ctx
from backend.errors import ApiError
from backend.routers.public import remember_items
from backend.tools.kakao import KakaoError

router = APIRouter(tags=["searches"])
log = logging.getLogger("dasimanna.searches")

LOCATION_LIMIT_PER_MINUTE = 30
PHOTO_ANALYSIS_LIMIT_PER_MINUTE = 5
TEXT_REFINEMENT_LIMIT_PER_MINUTE = 5


def _deps(ctx: AppContext) -> dict[str, Any]:
    return {"settings": ctx.settings, "store": ctx.store, "animal": ctx.animal, "kakao": ctx.kakao, "llm": ctx.llm,
            "embedder": ctx.embedder, "search_cache": ctx.search_cache, "search_agent": ctx.search_agent, "breed_normalizer": ctx.breed_normalizer}


def page_result(run, page=1, page_size=20):
    candidates = run.get("candidates") or []
    total = len(candidates)
    pages = max(1, (total + page_size - 1) // page_size)
    if page > pages:
        raise ApiError(422, "invalid_page", "검색 결과 페이지 범위를 벗어났습니다.")
    return {**run, "candidates": candidates[(page - 1) * page_size:page * page_size],
            "pagination": {"page": page, "page_size": page_size, "total": total, "pages": pages}}


@router.post("/searches")
async def create_search(body: SearchBody, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    refinement = await refinement_store.load(ctx.sessions._redis, user.owner, body.refinement_id)
    if body.refinement_id and (not refinement or refinement.get("description") != body.criteria.description):
        raise ApiError(422, "invalid_refinement", "다듬은 내용이 만료되었거나 검색 입력과 달라요. 다시 다듬어 주세요.")
    request = {
        "criteria": body.criteria.model_dump(exclude_none=True),
        "thread_id": body.thread_id,
        "profile_id": body.profile_id,
        "reflection_enabled": body.reflection_enabled,
        "declined": body.declined,
        # 사진 분석 번호로 서버가 보관한 결과를 꺼낸다(설명 글 속 사진 문장은 판단에 쓰지 않는다).
        "photo": refinement.get("photo_features") if refinement else await _load_photo(ctx, user.owner, body.photo_analysis_id),
        "precomputed_features": refinement.get("features") if refinement else None,
        "features_precomputed": bool(refinement),
    }
    run = await run_search(_deps(ctx), user.owner, request)
    remember_items(run.get("candidates") or [])
    return page_result(run)


@router.post("/searches/refine", response_model=RefineDescriptionResponse)
async def refine_description(body: RefineDescriptionBody, user: SessionUser = Depends(current_user),
                             ctx: AppContext = Depends(get_ctx)):
    """One text+optional-photo model call; the returned feature data is kept server-side for the next search."""
    llm = ctx.photo_llm
    if not llm or not hasattr(llm, "refine_description"):
        raise ApiError(503, "text_refinement_not_configured", "텍스트 다듬기 기능을 사용할 수 없습니다.")
    try:
        limited = await ctx.sessions.hit_rate_limit(f"text-refine:{user.owner}", TEXT_REFINEMENT_LIMIT_PER_MINUTE, 60)
    except AuthUnavailable:
        raise ApiError(503, "auth_unavailable", "로그인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if limited:
        raise ApiError(429, "text_refinement_rate_limited", "텍스트 다듬기 요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.")
    redis = ctx.sessions._redis
    token = secrets.token_hex(16)
    try:
        acquired = await refinement_store.begin(redis, user.owner, body.description, token)
    except Exception:
        raise ApiError(503, "text_refinement_unavailable", "텍스트 다듬기 기능에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if not acquired:
        raise ApiError(409, "text_refinement_in_progress", "같은 내용의 텍스트를 다듬고 있어요.")
    try:
        image_data = None
        mime_type = None
        photo_provided = body.image_base64 is not None or body.post_id is not None
        try:
            if body.image_base64 is not None or body.post_id is not None:
                encoded = body.image_base64 if body.image_base64 is not None else await _post_photo_base64(ctx, body.post_id)
                image_data, mime_type = decode_and_validate(encoded)
                image_data, mime_type = shrink_for_analysis(image_data, mime_type)
        except Exception as exc:
            # 사진 전송·추출에 실패해도 원문만으로 텍스트를 정리한다.
            image_data = mime_type = None
            log.info("refinement photo unavailable; continuing with text only (%s)", type(exc).__name__)
        try:
            result = await llm.refine_description(body.description, image_data, mime_type)
        except LlmError as exc:
            raise ApiError(502, exc.code, "텍스트를 다듬지 못했습니다. 잠시 후 다시 시도해 주세요.")
        stored = {
            "description": result.description,
            "features": result.features,
            "photo_features": result.photo_features,
        }
        try:
            refinement_id = await refinement_store.save(redis, user.owner, stored)
        except Exception:
            log.warning("refinement result store failed")
            raise ApiError(503, "text_refinement_unavailable", "다듬은 결과를 검색에 전달하지 못했습니다. 다시 시도해 주세요.")
        return RefineDescriptionResponse(description=result.description, refinement_id=refinement_id,
                                         photo_used=image_data is not None and not (photo_provided and result.photo_features is None))
    finally:
        try:
            await refinement_store.finish(redis, user.owner, body.description, token)
        except Exception:
            log.warning("refinement lock release failed")


async def _load_photo(ctx: AppContext, owner: str, analysis_id: str | None):
    if not analysis_id:
        return None
    try:
        return await photo_store.load(ctx.sessions._redis, owner, analysis_id)
    except Exception:  # Redis 장애면 사진 없이 검색한다
        log.warning("photo analysis load failed")
        return None


@router.post("/photo-analysis", response_model=PhotoAnalysisResponse)
async def analyze_photo(
    body: PhotoAnalysisBody,
    user: SessionUser = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
):
    if not ctx.photo_llm:
        raise ApiError(503, "photo_analysis_not_configured", "사진 분석 기능을 사용할 수 없습니다.")
    try:
        limited = await ctx.sessions.hit_rate_limit(f"photo-analysis:{user.owner}", PHOTO_ANALYSIS_LIMIT_PER_MINUTE, 60)
    except AuthUnavailable:
        raise ApiError(503, "auth_unavailable", "로그인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if limited:
        raise ApiError(429, "photo_analysis_rate_limited", "사진 분석 요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.")
    try:
        encoded = body.image_base64 if body.image_base64 is not None else await _post_photo_base64(ctx, body.post_id)
        image_data, mime_type = decode_and_validate(encoded)
        # 분석 시간을 줄이려고 긴 변 1024px 로 줄여 보낸다(직접 올린 사진·게시글 사진 공통).
        image_data, mime_type = shrink_for_analysis(image_data, mime_type)
    except InvalidPhoto as exc:
        raise ApiError(422, exc.code, exc.message)
    started = time.perf_counter()
    try:
        result = await ctx.photo_llm.analyze_photo(image_data, mime_type)
    except LlmError as exc:
        raise ApiError(502, exc.code, "사진을 분석하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    analysis_id = None
    try:
        # 검색 때 번호로 꺼내 쓰도록 결과(특징만)를 잠시 보관한다. 보관에 실패해도 분석 결과는 돌려준다.
        analysis_id = await photo_store.save(ctx.sessions._redis, user.owner, result.model_dump())
    except Exception:  # Redis 장애는 분석 자체를 막지 않는다
        log.warning("photo analysis store failed")
    return PhotoAnalysisResponse(
        **result.model_dump(),
        analysis_ms=round((time.perf_counter() - started) * 1000),
        analysis_id=analysis_id,
    )


async def _post_photo_base64(ctx: AppContext, post_id: str) -> str:
    """실종 정보 게시판 글의 사진을 base64 로 꺼낸다. 회원 글은 저장된 사진, 분실 신고는 공공데이터 사진을 서버가 받는다.

    사진 주소는 사용자가 보낸 값이 아니라 공공 API 응답에서 꺼낸 값만 쓴다(remote_photo 의 SSRF 방지 설명 참고).
    """
    from backend.routers.posts import BOARD_OWNER, KIND as POST_KIND, _LOST_ID

    if _LOST_ID.match(post_id):
        if ctx.lost is None:
            raise ApiError(503, "lost_board_unavailable", "분실 신고 정보를 불러올 수 없어요.")
        item = await ctx.lost.get(post_id)
        if not item or not item.get("photo_url"):
            raise ApiError(404, "photo_not_found", "사진이 없는 게시글입니다.")
        raw = await remote_photo.fetch_photo(item["photo_url"])
        return base64.b64encode(raw).decode()
    data = await ctx.store.get(BOARD_OWNER, POST_KIND, post_id)
    photo = (data or {}).get("photo")
    if not photo or not photo.get("data"):
        raise ApiError(404, "photo_not_found", "사진이 없는 게시글입니다.")
    return photo["data"]


@router.get("/runs")
async def list_runs(limit: int = Query(default=20, ge=1, le=50), user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    rows = await ctx.store.list(user.owner, "run", limit)
    out = []
    for row in rows:
        run = row["data"]
        out.append(
            {
                "run_id": run.get("run_id"),
                "thread_id": run.get("thread_id"),
                "status": run.get("status"),
                "criteria": run.get("criteria"),
                "candidate_count": len(run.get("candidates") or []),
                "reflection_count": run.get("reflection_count", 0),
                "data_source": run.get("data_source"),
                "created_at": run.get("created_at"),
            }
        )
    return {"runs": out}


async def _owned_run(ctx: AppContext, user: SessionUser, run_id: str) -> dict:
    run = await ctx.store.get(user.owner, "run", run_id)
    if not run:
        raise ApiError(404, "run_not_found", "실행 기록을 찾을 수 없습니다.")
    return run


@router.get("/runs/{run_id}")
async def get_run(run_id: str, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=40),
                  user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    run = await _owned_run(ctx, user, run_id)
    # 소유자를 저장소에서 확인한 뒤에만 조건 캐시를 읽는다. 만료 후에도 저장된 이력으로 페이지를 제공한다.
    if ctx.search_cache and run.get("cache_key"):
        snapshot = await ctx.search_cache.get(run["cache_key"])
        if snapshot and snapshot.get("snapshot_id") == run.get("snapshot_id"):
            run = {**run, "candidates": snapshot["candidates"]}
    return page_result(run, page, page_size)


@router.get("/runs/{run_id}/candidates/{candidate_id}/location")
async def candidate_location(
    run_id: str, candidate_id: str, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)
):
    try:
        limited = await ctx.sessions.hit_rate_limit(f"location:{user.owner}", LOCATION_LIMIT_PER_MINUTE, 60)
    except AuthUnavailable:
        raise ApiError(503, "auth_unavailable", "로그인 서버에 연결할 수 없습니다.")
    if limited:
        raise ApiError(429, "location_rate_limited", "위치 조회가 너무 잦습니다. 잠시 후 다시 시도해 주세요.")
    run = await _owned_run(ctx, user, run_id)
    candidates = run.get("candidates") or []
    candidate = next((c for c in candidates if c.get("id") == candidate_id), None)
    if not candidate:
        raise ApiError(404, "candidate_not_found", "후보를 찾을 수 없습니다.")
    if candidate.get("source") == "sample":
        return {"status": "unavailable", "reason": "sample"}
    address = (candidate.get("care") or {}).get("address")
    cached = candidate.get("location") or {}
    if cached.get("status") == "ok" and cached.get("address") == (address or "").strip():
        return {**cached, "cached": True}
    try:
        result = await ctx.kakao.geocode(address)
    except KakaoError as exc:
        # 오류는 캐시하지 않는다.
        raise ApiError(502, exc.code, "보호센터 위치를 확인하지 못했습니다. 다시 시도해 주세요.")
    if result["status"] == "ok":
        candidate["location"] = result
        await ctx.store.put(user.owner, "run", run_id, run)
    return {**result, "cached": False}


@router.get("/runs/{run_id}/candidates/{candidate_id}")
async def candidate_detail(run_id: str, candidate_id: str, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    run = await _owned_run(ctx, user, run_id)
    candidate = next((c for c in run.get("candidates") or [] if c["id"] == candidate_id), None)
    if not candidate:
        raise ApiError(404, "candidate_not_found", "후보를 찾을 수 없습니다.")
    return candidate
