"""실종 정보 게시판: /posts (디자인: dasimanna-cards-board.html · dasimanna-cards-post-detail.html).

- 목록·상세·사진은 로그인 없이 읽는다(공개 게시판). 작성은 로그인 사용자만, 삭제는 작성자만 한다.
- 게시글은 사용자별 문서가 아니라 공용 소유자 키(BOARD_OWNER) 아래 kind=post 로 저장한다.
  작성자 키(로그인 사용자 owner)는 data.author 에만 두고 응답에 내보내지 않는다(mine 여부만 알려 준다).
- 연락처는 받지 않는다. 사진은 브라우저에서 줄인 JPEG/PNG/WebP 를 data URL 로 받아 크기·형식을 검사한다.
"""

from __future__ import annotations

import base64
import binascii
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from backend.auth.sessions import AuthUnavailable, SessionUser
from backend.deps import COOKIE_NAME, AppContext, current_user, get_ctx
from backend.errors import ApiError
from backend.schemas.api import MAX_POST_PHOTO_BYTES, PostBody

router = APIRouter(tags=["posts"])

BOARD_OWNER = "board"  # 공용 게시판 소유자 키(사용자 owner 는 64자 SHA-256 이므로 겹치지 않는다)
KIND = "post"
LIST_SCAN = 200
LIST_LIMIT = 60
MAX_POSTS_PER_USER = 10
MAX_PHOTO_BYTES = MAX_POST_PHOTO_BYTES
MAX_LOST_DAYS = 365
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
_DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\s]+)$")
_POST_ID = re.compile(r"^[0-9a-f]{32}$")

KST = timezone(timedelta(hours=9))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def kst_today() -> date:
    """실종 날짜 검사 기준일. 서버(UTC)와 사용자(한국) 날짜가 다른 새벽 시간대에도 오늘을 허용한다."""
    return datetime.now(KST).date()


def _decode_photo(photo: str) -> tuple[str, bytes]:
    match = _DATA_URL.match(photo)
    if not match:
        raise ApiError(422, "photo_invalid", "사진은 JPG·PNG·WebP 이미지만 올릴 수 있어요.")
    try:
        raw = base64.b64decode(re.sub(r"\s", "", match.group(2)), validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(422, "photo_invalid", "사진 파일을 읽지 못했어요.")
    if len(raw) > MAX_PHOTO_BYTES:
        raise ApiError(413, "photo_too_large", "사진이 너무 커요. 400KB 이하로 줄여 주세요.")
    return match.group(1), raw


def _public(post_id: str, data: dict, viewer: str | None, *, detail: bool) -> dict:
    out = {
        "id": post_id,
        "pet_name": data["pet_name"],
        "species": data["species"],
        "region": data["region"],
        "lost_place": data.get("lost_place", ""),
        "lost_date": data["lost_date"],
        "breed": data.get("breed", ""),
        "has_photo": bool(data.get("photo")),
        "created_at": data["created_at"],
        "mine": viewer is not None and data.get("author") == viewer,
    }
    if detail:
        out["description"] = data["description"]
    else:
        text = data["description"]
        out["summary"] = text if len(text) <= 80 else text[:80] + "…"
    return out


async def _viewer(request: Request, ctx: AppContext) -> str | None:

    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        user = await ctx.sessions.get(token)
    except AuthUnavailable:
        return None
    return user.owner if user else None


async def _get(ctx: AppContext, post_id: str) -> dict:
    if not _POST_ID.match(post_id):
        raise ApiError(404, "post_not_found", "게시글을 찾을 수 없습니다.")
    data = await ctx.store.get(BOARD_OWNER, KIND, post_id)
    if not data:
        raise ApiError(404, "post_not_found", "게시글을 찾을 수 없습니다.")
    return data


@router.get("/posts")
async def list_posts(
    request: Request,
    species: Literal["all", "dog", "cat", "etc"] = "all",
    region: str = Query(default="", max_length=20),
    ctx: AppContext = Depends(get_ctx),
):
    viewer = await _viewer(request, ctx)
    rows = await ctx.store.list(BOARD_OWNER, KIND, LIST_SCAN)
    items = []
    for row in rows:
        data = row["data"]
        if species != "all" and data["species"] != species:
            continue
        if region and data["region"] != region:
            continue
        items.append(_public(row["id"], data, viewer, detail=False))
        if len(items) >= LIST_LIMIT:
            break
    return {"items": items, "count": len(items), "scanned": len(rows), "scan_limit": LIST_SCAN}


@router.get("/posts/mine")
async def list_my_posts(user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):

    rows = await ctx.store.list(BOARD_OWNER, KIND, LIST_SCAN)
    items = [_public(r["id"], r["data"], user.owner, detail=False) for r in rows if r["data"].get("author") == user.owner]
    return {"items": items, "count": len(items), "limit": MAX_POSTS_PER_USER}


@router.get("/posts/{post_id}")
async def get_post(post_id: str, request: Request, ctx: AppContext = Depends(get_ctx)):
    data = await _get(ctx, post_id)
    return _public(post_id, data, await _viewer(request, ctx), detail=True)


@router.get("/posts/{post_id}/photo")
async def get_post_photo(post_id: str, ctx: AppContext = Depends(get_ctx)):
    data = await _get(ctx, post_id)
    photo = data.get("photo")
    if not photo or photo.get("type") not in PHOTO_TYPES:
        raise ApiError(404, "photo_not_found", "사진이 없는 게시글입니다.")
    raw = base64.b64decode(photo["data"])
    # 미들웨어가 /api/v1 응답에 no-store 를 붙인다. 사진은 게시글 삭제 시 바로 사라져야 하므로 그대로 둔다.
    return Response(content=raw, media_type=photo["type"], headers={"X-Content-Type-Options": "nosniff"})


@router.post("/posts", status_code=201)
async def create_post(body: PostBody, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    today = kst_today()
    if body.lost_date > today:
        raise ApiError(422, "lost_date_future", "실종 날짜가 오늘 이후일 수 없어요.")
    if body.lost_date < today - timedelta(days=MAX_LOST_DAYS):
        raise ApiError(422, "lost_date_too_old", "실종 날짜는 최근 1년 이내만 등록할 수 있어요.")
    if not body.pet_name or not body.region or len(body.description) < 5:
        raise ApiError(422, "invalid_request", "입력값을 확인해 주세요.")
    if body.region in ("전체", "all"):
        raise ApiError(422, "region_required", "실종 위치를 지도에서 선택해 주세요.")
    photo = None
    if body.photo:
        media_type, raw = _decode_photo(body.photo)
        photo = {"type": media_type, "data": base64.b64encode(raw).decode(), "bytes": len(raw)}

    rows = await ctx.store.list(BOARD_OWNER, KIND, LIST_SCAN)
    if sum(1 for r in rows if r["data"].get("author") == user.owner) >= MAX_POSTS_PER_USER:
        raise ApiError(429, "post_limit", f"게시글은 한 사람당 {MAX_POSTS_PER_USER}개까지 올릴 수 있어요. 이전 글을 지운 뒤 다시 등록해 주세요.")

    post_id = uuid.uuid4().hex
    data = {
        "pet_name": body.pet_name,
        "species": body.species,
        "region": body.region,
        "lost_place": body.lost_place,
        "lost_date": body.lost_date.isoformat(),
        "breed": body.breed,
        "description": body.description,
        "photo": photo,
        "author": user.owner,
        "created_at": _now(),
    }
    await ctx.store.put(BOARD_OWNER, KIND, post_id, data)
    return _public(post_id, data, user.owner, detail=True)


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: str, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    data = await _get(ctx, post_id)
    if data.get("author") != user.owner:
        # 남의 글은 존재 여부와 관계없이 지울 수 없다.
        raise ApiError(403, "post_forbidden", "내가 쓴 글만 지울 수 있어요.")
    await ctx.store.delete(BOARD_OWNER, KIND, post_id)
