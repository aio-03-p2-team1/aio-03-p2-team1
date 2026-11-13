"""검색·실행 이력·보호센터 위치 API (로그인 필요, 소유자 격리)."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.agent.llm import LlmError
from backend.agent.photo import MAX_IMAGE_BYTES, InvalidPhoto, decode_and_validate
from backend.agent.runner import run_search
from backend.auth.sessions import AuthUnavailable, SessionUser
from backend.deps import AppContext, current_user, get_ctx
from backend.errors import ApiError
from backend.routers.public import remember_items
from backend.tools.kakao import KakaoError

router = APIRouter(tags=["searches"])

LOCATION_LIMIT_PER_MINUTE = 30
PHOTO_ANALYSIS_LIMIT_PER_MINUTE = 5


class SearchCriteria(BaseModel):
    species: str | None = Field(default=None, max_length=10)
    region: str | None = Field(default=None, max_length=30)
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    lost_date: str | None = Field(default=None, max_length=10)
    pet_name: str | None = Field(default=None, max_length=30)
    breed: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=40)
    sex: str | None = Field(default=None, max_length=4)
    age: str | None = Field(default=None, max_length=20)
    size: str | None = Field(default=None, max_length=20)
    lost_place: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class SearchBody(BaseModel):
    criteria: SearchCriteria = SearchCriteria()
    thread_id: str | None = Field(default=None, max_length=64, pattern=r"^[0-9a-f]{8,64}$")
    profile_id: str | None = Field(default=None, max_length=40, pattern=r"^[\w-]{1,40}$")
    reflection_enabled: bool = True


class PhotoAnalysisBody(BaseModel):
    image_base64: str = Field(min_length=1, max_length=((MAX_IMAGE_BYTES + 2) // 3) * 4)


def _deps(ctx: AppContext) -> dict[str, Any]:
    return {"settings": ctx.settings, "store": ctx.store, "animal": ctx.animal, "kakao": ctx.kakao, "llm": ctx.llm}


@router.post("/searches")
async def create_search(body: SearchBody, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    request = {
        "criteria": body.criteria.model_dump(exclude_none=True),
        "thread_id": body.thread_id,
        "profile_id": body.profile_id,
        "reflection_enabled": body.reflection_enabled,
    }
    run = await run_search(_deps(ctx), user.owner, request)
    remember_items(run.get("candidates") or [])
    return run


@router.post("/photo-analysis")
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
        image_data, mime_type = decode_and_validate(body.image_base64)
    except InvalidPhoto as exc:
        raise ApiError(422, exc.code, exc.message)
    started = time.perf_counter()
    try:
        result = await ctx.photo_llm.analyze_photo(image_data, mime_type)
    except LlmError as exc:
        raise ApiError(502, exc.code, "사진을 분석하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    result["analysis_ms"] = round((time.perf_counter() - started) * 1000)
    return result


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
async def get_run(run_id: str, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return await _owned_run(ctx, user, run_id)


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
    address = (candidate.get("care") or {}).get("address")  # 클라이언트 입력이 아닌 저장된 결과에서 읽는다
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
