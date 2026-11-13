"""저장 검색과 사용자 기억 (로그인 필요, 소유자 격리)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.auth.sessions import SessionUser
from backend.deps import AppContext, current_user, get_ctx
from backend.errors import ApiError
from backend.routers.searches import SearchCriteria

router = APIRouter(tags=["memory"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SavedSearchBody(BaseModel):
    title: str = Field(default="", max_length=40)
    criteria: SearchCriteria


@router.get("/saved-searches")
async def list_saved(user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    rows = await ctx.store.list(user.owner, "saved", 50)
    return {"saved_searches": [{"key": r["id"], **r["data"]} for r in rows]}


@router.post("/saved-searches", status_code=201)
async def create_saved(body: SavedSearchBody, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    key = uuid.uuid4().hex
    data = {"title": body.title.strip(), "criteria": body.criteria.model_dump(exclude_none=True), "created_at": _now()}
    await ctx.store.put(user.owner, "saved", key, data)
    return {"key": key, **data}


@router.delete("/saved-searches/{key}", status_code=204)
async def delete_saved(key: str, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    if not await ctx.store.delete(user.owner, "saved", key):
        raise ApiError(404, "saved_search_not_found", "저장한 검색을 찾을 수 없습니다.")


class MemoryBody(BaseModel):
    profile_id: str = Field(pattern=r"^[\w-]{1,40}$")
    # 사용자가 직접 확인한 특징만 저장한다(모델 추정값 금지).
    confirmed: SearchCriteria


@router.get("/memory/{profile_id}")
async def get_memory(profile_id: str, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    memory = await ctx.store.get(user.owner, "memory", profile_id)
    if not memory:
        raise ApiError(404, "memory_not_found", "저장된 동물 프로필이 없습니다.")
    return memory


@router.put("/memory")
async def put_memory(body: MemoryBody, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    confirmed = body.confirmed.model_dump(exclude_none=True)
    for key in ("species", "region", "start_date", "end_date"):
        confirmed.pop(key, None)  # 검색 범위는 장기 기억에 넣지 않는다
    data = {"profile_id": body.profile_id, "confirmed": confirmed, "updated_at": _now()}
    await ctx.store.put(user.owner, "memory", body.profile_id, data)
    return data


@router.delete("/memory/{profile_id}", status_code=204)
async def delete_memory(profile_id: str, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    if not await ctx.store.delete(user.owner, "memory", profile_id):
        raise ApiError(404, "memory_not_found", "저장된 동물 프로필이 없습니다.")
