"""실종 정보 게시판: /posts (디자인: dasimanna-cards-board.html · dasimanna-cards-post-detail.html).

- 목록·상세·사진은 로그인 없이 읽는다(공개 게시판). 작성은 로그인 사용자만, 삭제는 작성자만 한다.
- 게시글은 사용자별 문서가 아니라 공용 소유자 키(BOARD_OWNER) 아래 kind=post 로 저장한다.
  작성자 키(로그인 사용자 owner)는 data.author 에만 두고 응답에 내보내지 않는다(mine 여부만 알려 준다).
- 연락처는 받지 않는다. 사진은 브라우저에서 줄인 JPEG/PNG/WebP 를 data URL 로 받아 크기·형식을 검사한다.
- 목록에는 회원 글과 공공데이터 분실 신고(ctx.lost, backend/tools/lost_feed.py)를 분실 날짜순으로 합쳐 보여 준다.
  분실 신고는 개인정보(신고자·연락처·칩 번호·상세 주소)를 뺀 형태로만 다룬다. 회원 글 작성·삭제 규칙은 그대로다.
- 분실 신고 호출이 실패해도 회원 글은 보여 주고, 응답의 lost.status 로 실패를 알린다(빈 결과로 위장하지 않음).
"""

from __future__ import annotations

import asyncio
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
from backend.tools.lost_animal_api import LostAnimalApiError

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
_LOST_ID = re.compile(r"^lost-\d{8}-[0-9a-f]{12}$")  # lost_animal_api.lost_id() 형식
PAGE_ROWS = 20  # 목록 한 페이지 글 수
LOST_WAIT_SECONDS = 8  # 분실 신고 첫 조회를 기다리는 최대 시간. 넘으면 회원 글 먼저 보여 주고 조회는 계속한다

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
        "source": "member",  # 회원이 직접 쓴 글(분실 신고는 "lost_api")
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
    days: int = Query(default=30, ge=1, le=90),  # 분실 날짜 기준 최근 며칠
    page: int = Query(default=1, ge=1, le=100),
    ctx: AppContext = Depends(get_ctx),
):
    """회원 글 + 분실 신고를 분실 날짜 최신순으로 합쳐 PAGE_ROWS 개씩 돌려준다.

    필터·정렬·페이지 나누기는 모두 서버 메모리에서 한다. 분실 신고는 기간별 캐시(LostFeed)에서 꺼내므로
    필터를 바꾸거나 페이지를 넘겨도 외부 API 를 다시 부르지 않는다.
    """
    end = kst_today()
    start = end - timedelta(days=days)

    # 회원 글 조회(DB)와 분실 신고 조회(외부 API·캐시)를 동시에 시작한다.
    member_task = asyncio.create_task(ctx.store.list(BOARD_OWNER, KIND, LIST_SCAN))
    lost_items, lost_info = await _lost_items(ctx, start, end)
    rows = await member_task
    viewer = await _viewer(request, ctx)

    def keep(item: dict) -> bool:
        if species != "all" and item["species"] != species:
            return False
        # 회원 글 region 은 시도 이름, 분실 신고 region 은 "시도 시군구" → 앞부분으로 비교한다.
        if region and not str(item.get("region") or "").startswith(region):
            return False
        return bool(item.get("lost_date")) and item["lost_date"] >= start.isoformat()

    members = [_public(r["id"], r["data"], viewer, detail=False) for r in rows]
    merged = [i for i in members if keep(i)] + [i for i in lost_items if keep(i)]
    # 분실 날짜 최신순. 같은 날이면 회원 글을 먼저 보여 준다.
    merged.sort(key=lambda i: (i["lost_date"], i["source"] == "member"), reverse=True)

    pages = max(1, -(-len(merged) // PAGE_ROWS))
    page = min(page, pages)
    chunk = merged[(page - 1) * PAGE_ROWS: page * PAGE_ROWS]
    return {
        "items": [_list_view(i) for i in chunk],
        "count": len(merged),  # 조건에 맞는 전체 글 수
        "member_count": sum(1 for i in merged if i["source"] == "member"),
        "lost_count": sum(1 for i in merged if i["source"] == "lost_api"),
        "page": page,
        "pages": pages,
        "rows": PAGE_ROWS,
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "lost": lost_info,
        "scanned": len(rows),
        "scan_limit": LIST_SCAN,
    }


def _list_view(item: dict) -> dict:
    """목록 카드에 필요 없는 긴 필드(상세 설명)는 빼고 보낸다(응답 크기 줄이기)."""
    return {k: v for k, v in item.items() if k != "description"}


async def _lost_items(ctx: AppContext, start: date, end: date) -> tuple[list[dict], dict]:
    """분실 신고 목록과 상태. 키가 없거나 호출이 실패하면 빈 목록 + 상태(status)로 알린다."""
    if ctx.lost is None:
        return [], {"status": "not_configured"}
    try:
        # shield: 기다리기를 그만둬도 조회 자체는 계속 진행돼 캐시에 들어간다(다음 새로고침에서 바로 보임).
        task = asyncio.ensure_future(ctx.lost.snapshot(start, end))
        task.add_done_callback(_consume_error)
        snap = await asyncio.wait_for(asyncio.shield(task), LOST_WAIT_SECONDS)
    except asyncio.TimeoutError:
        return [], {"status": "loading", "message": "공공데이터 분실 신고를 불러오는 중이에요. 잠시 후 새로고침해 주세요."}
    except LostAnimalApiError as exc:
        return [], {"status": "unavailable", "error_code": exc.code,
                    "message": "공공데이터 분실 신고를 불러오지 못했어요. 회원 글만 보여 드려요."}
    return snap.items, {"status": "ok", "total_count": snap.total_count, "received": len(snap.items),
                        "truncated": snap.truncated}


def _consume_error(task: asyncio.Task) -> None:
    # 기다리기를 그만둔 뒤 조회가 실패해도 'exception was never retrieved' 경고가 남지 않게 한다.
    if not task.cancelled():
        task.exception()


@router.get("/posts/lost/{lost_id}")
async def get_lost_report(lost_id: str, ctx: AppContext = Depends(get_ctx)):
    """공공데이터 분실 신고 상세. 개인정보가 빠진 형태만 돌려준다."""
    if ctx.lost is None or not _LOST_ID.match(lost_id):
        raise ApiError(404, "post_not_found", "게시글을 찾을 수 없습니다.")
    try:
        item = await ctx.lost.get(lost_id)
    except LostAnimalApiError as exc:
        raise ApiError(502, exc.code, "공공데이터 분실 신고를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.")
    if not item:
        raise ApiError(404, "post_not_found", "게시글을 찾을 수 없습니다.")
    return item


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
