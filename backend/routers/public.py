from __future__ import annotations

import time
from collections import OrderedDict
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query

from backend.deps import AppContext, get_ctx
from backend.errors import ApiError
from backend.tools.animal_api import AnimalApiError

router = APIRouter(tags=["public"])

_LIST_TTL = 120
_MAX_DETAIL = 3000
_list_cache: dict[tuple, tuple[float, dict]] = {}
_detail_cache: "OrderedDict[str, dict]" = OrderedDict()

ANIMAL_ERROR_STATUS = {"animal_auth": 502, "animal_rate_limit": 503, "animal_timeout": 504}


def _remember(items: list[dict]) -> None:
    for item in items:
        if not item.get("id"):
            continue
        _detail_cache[item["id"]] = item
        _detail_cache.move_to_end(item["id"])
    while len(_detail_cache) > _MAX_DETAIL:
        _detail_cache.popitem(last=False)


def remember_items(items: list[dict]) -> None:

    _remember(items)


@router.get("/health")
async def health(ctx: AppContext = Depends(get_ctx)):
    s = ctx.settings
    return {
        "status": "ok",
        "mode": s.app_mode,
        "storage": s.storage_backend,
        "model": s.openai_model if s.app_mode == "live" else None,
        "animal_data_source": s.animal_data_source,
        "kakao_configured": ctx.kakao.configured,
        "lost_data_source": "api" if ctx.lost is not None else "off",  # 게시판 분실 신고 연동 여부
        "notifications": "not_implemented",
    }


def _animal_error(exc: AnimalApiError) -> ApiError:
    from backend.agent.graph import ERROR_MESSAGES

    return ApiError(ANIMAL_ERROR_STATUS.get(exc.code, 502), exc.code, ERROR_MESSAGES.get(exc.code, exc.code))


@router.get("/regions")
async def regions(ctx: AppContext = Depends(get_ctx)):
    try:
        items = await ctx.animal.regions()
    except AnimalApiError as exc:
        raise _animal_error(exc)
    return {"data_source": ctx.animal.source, "regions": [{"code": r.code, "name": r.name} for r in items]}


@router.get("/notices")
async def notices(
    species: Literal["all", "dog", "cat", "etc"] = "all",
    region_code: str | None = Query(default=None, max_length=20),
    days: int = Query(default=14, ge=1, le=60),
    page: int = Query(default=1, ge=1, le=20),
    rows: int = Query(default=20, ge=4, le=40),
    ctx: AppContext = Depends(get_ctx),
):
    end = date.today()
    start = end - timedelta(days=days)
    key = (ctx.animal.source, species, region_code, start, end, page, rows)
    cached = _list_cache.get(key)
    if cached and time.monotonic() - cached[0] < _LIST_TTL:
        return cached[1]
    try:
        result = await ctx.animal.search(
            region_code=region_code or None, start=start, end=end, species=species, page=page, rows=rows
        )
    except AnimalApiError as exc:
        raise _animal_error(exc)
    _remember(result.items)
    body = {
        "data_source": result.source,
        "fetched_at": result.fetched_at,
        "total_count": result.total_count,
        "page": page,
        "rows": rows,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "items": result.items,
    }
    _list_cache[key] = (time.monotonic(), body)
    if len(_list_cache) > 200:
        _list_cache.pop(next(iter(_list_cache)))
    return body


@router.get("/notices/{notice_id}")
async def notice_detail(notice_id: str):
    item = _detail_cache.get(notice_id)
    if not item:
        raise ApiError(404, "notice_not_cached", "공고 정보를 다시 불러와야 합니다. 목록에서 공고를 다시 선택해 주세요.")
    return item
