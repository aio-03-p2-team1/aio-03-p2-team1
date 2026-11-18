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
import html
import io
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from mutagen import File as MutagenFile

from backend.auth.sessions import AuthUnavailable, SessionUser
from backend.deps import COOKIE_NAME, AppContext, current_user, get_ctx
from backend.errors import ApiError
from backend.schemas.api import MAX_POST_PHOTO_BYTES, PostBody, PostUpdateBody
from backend.timeutil import kst_today  # noqa: F401  (tests 에서 posts.kst_today 로도 import)
from backend.tools.lost_animal_api import LostAnimalApiError
from backend.tools.kinds import normalize
from backend.tools.kind_aliases import is_curated_alias

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
PAGE_ROWS = 21  # 목록 한 페이지 글 수(3열 카드 7줄)
LOST_WAIT_SECONDS = 8  # 분실 신고 첫 조회를 기다리는 최대 시간. 넘으면 회원 글 먼저 보여 주고 조회는 계속한다
MAX_POST_VOICES = 3
MAX_VOICE_BYTES = 10 * 1024 * 1024
MAX_VOICE_SECONDS = 60
VOICE_TYPES = {
    "MP3": ("audio/mpeg", "mp3"),
    "MP4": ("audio/mp4", "m4a"),
    "WAVE": ("audio/wav", "wav"),
    "OggVorbis": ("audio/ogg", "ogg"),
    "OggOpus": ("audio/ogg", "ogg"),
}



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# kst_today 는 backend.timeutil 로 옮겼다(검색·게시판이 같은 기준을 쓴다). 기존 import 경로를 위해 다시 내보낸다.


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
        "breed_code": data.get("breed_code", ""),
        "has_photo": bool(data.get("photo")),
        "created_at": data["created_at"],
        "mine": viewer is not None and data.get("author") == viewer,
    }
    if detail:
        out["description"] = data["description"]
        out["voices"] = [_public_voice(voice) for voice in data.get("voices", [])]
    else:
        text = data["description"]
        out["summary"] = text if len(text) <= 80 else text[:80] + "…"
    return out


def _public_voice(voice: dict) -> dict:
    return {
        "id": voice["id"],
        "description": html.unescape(voice["description"]),
        "content_type": voice["content_type"],
        "size": voice["size"],
        "duration": voice["duration"],
    }


def _validated_voice(raw: bytes) -> tuple[str, str, float]:
    try:
        parsed = MutagenFile(io.BytesIO(raw))
    except Exception as exc:
        raise ApiError(422, "voice_invalid", "음성 파일을 읽을 수 없어요.") from exc
    if parsed is None or type(parsed).__name__ not in VOICE_TYPES or not getattr(parsed, "info", None):
        raise ApiError(422, "voice_invalid", "MP3·M4A·WAV·OGG 음성 파일만 올릴 수 있어요.")
    duration = float(getattr(parsed.info, "length", 0) or 0)
    channels = getattr(parsed.info, "channels", None)
    if duration <= 0 or not channels:
        raise ApiError(422, "voice_invalid", "음성 파일 정보를 확인할 수 없어요.")
    if duration > MAX_VOICE_SECONDS:
        raise ApiError(422, "voice_too_long", "음성은 1분 이내만 올릴 수 있어요.")
    content_type, extension = VOICE_TYPES[type(parsed).__name__]
    return content_type, extension, duration


async def _read_voice(upload: UploadFile) -> bytes:
    raw = await upload.read(MAX_VOICE_BYTES + 1)
    if not raw:
        raise ApiError(422, "voice_invalid", "음성 파일을 선택해 주세요.")
    if len(raw) > MAX_VOICE_BYTES:
        raise ApiError(413, "voice_too_large", "음성 파일은 하나당 10 MiB까지 올릴 수 있어요.")
    return raw


async def _with_breed_codes(items: list[dict], ctx: AppContext) -> list[dict]:
    """기존 회원 글·분실 신고도 축종별 공식명/별칭으로만 매핑한다. LLM 추측은 사용하지 않는다."""
    catalogs = {}
    result = []
    for item in items:
        saved_code = item.get("breed_code", "")
        item = {**item, "breed_code": ""}
        species = item.get("species")
        if ctx.kinds is not None and species in {"dog", "cat", "etc"} and (saved_code or item.get("breed")):
            if species not in catalogs:
                catalogs[species] = await ctx.kinds.rows(species)
            query = normalize(item.get("breed", ""))
            if saved_code:
                matches = {row["kind_code"] for row in catalogs[species] if row["kind_code"] == saved_code}
            else:
                # DB 별칭 행이 아직 동기화되지 않은 경우에도 큐레이션 원본을 적용한다.
                alias_matches = {row["kind_code"] for row in catalogs[species]
                                 if normalize(row.get("alias") or "") == query
                                 or is_curated_alias(row["name"], query)}
                matches = alias_matches or {row["kind_code"] for row in catalogs[species]
                                            if normalize(row["name"]) == query}
            if len(matches) == 1:
                item["breed_code"] = matches.pop()
        result.append(item)
    return result


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
        "items": await _with_breed_codes([_list_view(i) for i in chunk], ctx),
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
    return (await _with_breed_codes([item], ctx))[0]


@router.get("/posts/mine")
async def list_my_posts(user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):

    rows = await ctx.store.list(BOARD_OWNER, KIND, LIST_SCAN)
    items = [_public(r["id"], r["data"], user.owner, detail=False) for r in rows if r["data"].get("author") == user.owner]
    return {"items": await _with_breed_codes(items, ctx), "count": len(items), "limit": MAX_POSTS_PER_USER}


@router.get("/posts/{post_id}")
async def get_post(post_id: str, request: Request, ctx: AppContext = Depends(get_ctx)):
    data = await _get(ctx, post_id)
    return (await _with_breed_codes([_public(post_id, data, await _viewer(request, ctx), detail=True)], ctx))[0]


@router.patch("/posts/{post_id}")
async def update_post(post_id: str, body: PostUpdateBody, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    data = await _get(ctx, post_id)
    if data.get("author") != user.owner:
        raise ApiError(403, "post_forbidden", "내가 쓴 글만 수정할 수 있어요.")
    today = kst_today()
    if body.lost_date > today:
        raise ApiError(422, "lost_date_future", "실종 날짜가 오늘 이후일 수 없어요.")
    if body.lost_date < today - timedelta(days=MAX_LOST_DAYS):
        raise ApiError(422, "lost_date_too_old", "실종 날짜는 최근 1년 이내만 등록할 수 있어요.")
    if body.region in ("전체", "all"):
        raise ApiError(422, "region_required", "실종 위치를 지도에서 선택해 주세요.")
    if not body.pet_name or not body.region or len(body.description) < 5:
        raise ApiError(422, "invalid_request", "입력값을 확인해 주세요.")
    breed, breed_code = body.breed, ""
    if body.breed_code:
        if ctx.kinds is None:
            raise ApiError(503, "kinds_unavailable", "품종 목록을 불러오지 못했어요.")
        rows = await ctx.kinds.rows(body.species)
        row = next((r for r in rows if r["kind_code"] == body.breed_code), None)
        if row is None:
            raise ApiError(422, "invalid_breed_code", "선택한 축종의 품종 코드를 확인해 주세요.")
        breed, breed_code = row["name"], row["kind_code"]
    data.update(body.model_dump(exclude={"breed", "breed_code"}))
    data["lost_date"] = body.lost_date.isoformat()
    data["breed"], data["breed_code"] = breed, breed_code
    await ctx.store.put(BOARD_OWNER, KIND, post_id, data)
    return _public(post_id, data, user.owner, detail=True)


@router.post("/posts/{post_id}/voices", status_code=201)
async def add_post_voice(
    post_id: str,
    description: str = Form(...),
    audio: UploadFile = File(...),
    user: SessionUser = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
):
    data = await _get(ctx, post_id)
    if data.get("author") != user.owner:
        raise ApiError(403, "post_forbidden", "내가 쓴 글에만 음성을 추가할 수 있어요.")
    voices = list(data.get("voices", []))
    if len(voices) >= MAX_POST_VOICES:
        raise ApiError(422, "voice_limit", "게시글에는 음성을 최대 3개까지 올릴 수 있어요.")
    description = description.strip()
    if not description or len(description) > 200:
        raise ApiError(422, "voice_description_invalid", "음성 설명을 1~200자로 입력해 주세요.")
    raw = await _read_voice(audio)
    content_type, extension, duration = _validated_voice(raw)
    voice_id = uuid.uuid4().hex
    key = f"{post_id}/{uuid.uuid4().hex}.{extension}"
    await ctx.post_audio.put(key, raw, content_type)
    voice = {
        "id": voice_id,
        "key": key,
        "description": html.escape(description, quote=True),
        "content_type": content_type,
        "size": len(raw),
        "duration": duration,
    }
    voices.append(voice)
    data["voices"] = voices
    try:
        await ctx.store.put(BOARD_OWNER, KIND, post_id, data)
    except Exception:
        await ctx.post_audio.delete(key)
        raise
    return _public_voice(voice)


@router.get("/posts/{post_id}/voices/{voice_id}/audio")
async def get_post_voice(post_id: str, voice_id: str, ctx: AppContext = Depends(get_ctx)):
    data = await _get(ctx, post_id)
    voice = next((v for v in data.get("voices", []) if v["id"] == voice_id), None)
    if not voice:
        raise ApiError(404, "voice_not_found", "음성 파일을 찾을 수 없습니다.")
    raw = await ctx.post_audio.get(voice["key"])
    if raw is None:
        raise ApiError(404, "voice_not_found", "음성 파일을 찾을 수 없습니다.")
    return Response(content=raw, media_type=voice["content_type"], headers={"X-Content-Type-Options": "nosniff", "Accept-Ranges": "none"})


@router.delete("/posts/{post_id}/voices/{voice_id}", status_code=204)
async def delete_post_voice(post_id: str, voice_id: str, user: SessionUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    data = await _get(ctx, post_id)
    if data.get("author") != user.owner:
        raise ApiError(403, "post_forbidden", "내가 쓴 글의 음성만 삭제할 수 있어요.")
    voices = list(data.get("voices", []))
    voice = next((v for v in voices if v["id"] == voice_id), None)
    if not voice:
        raise ApiError(404, "voice_not_found", "음성 파일을 찾을 수 없습니다.")
    data["voices"] = [v for v in voices if v["id"] != voice_id]
    await ctx.store.put(BOARD_OWNER, KIND, post_id, data)
    await ctx.post_audio.delete(voice["key"])


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
    breed = body.breed
    breed_code = ""
    if body.breed_code:
        if ctx.kinds is None:
            raise ApiError(503, "kinds_unavailable", "품종 목록을 불러오지 못했어요.")
        rows = await ctx.kinds.rows(body.species)
        row = next((r for r in rows if r["kind_code"] == body.breed_code), None)
        if row is None:
            raise ApiError(422, "invalid_breed_code", "선택한 축종의 품종 코드를 확인해 주세요.")
        breed, breed_code = row["name"], row["kind_code"]
    elif breed:
        resolved = (await _with_breed_codes([{"species": body.species, "breed": breed}], ctx))[0]
        breed_code = resolved["breed_code"]
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
        "breed": breed,
        "breed_code": breed_code,
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
    for voice in data.get("voices", []):
        await ctx.post_audio.delete(voice["key"])
    # 글을 지우면 그 글의 댓글도 지운다(순환 import 를 피하려고 함수 안에서 불러온다).
    from backend.routers.comments import delete_all_comments

    await delete_all_comments(ctx, post_id)
