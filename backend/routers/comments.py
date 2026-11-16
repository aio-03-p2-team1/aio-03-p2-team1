"""실종 정보 게시판 댓글: /posts/{target_id}/comments.

- 대상 게시글은 회원 글(32자 ID)과 공공데이터 분실 신고(lost-YYYYMMDD-해시) 둘 다다.
  게시글 데이터는 저장하지 않고 댓글만 documents 테이블에 저장한다.
  저장 위치: owner="comment:<게시글 ID>", kind="comment", id=댓글 ID(32자).
- 읽기는 공개, 작성은 로그인 사용자만, 삭제는 작성자만 한다. 작성자 키는 data.author 에만 두고 응답에 내보내지 않는다.
- 본문의 전화번호는 분실 신고 설명과 같은 규칙(mask_contacts)으로 가린 뒤 저장한다.
- 분실 신고 ID 는 원본 값으로 계산한 것이라, 원본 신고가 수정되면 ID 가 바뀌어 기존 댓글이 그 글에 보이지 않을 수 있다.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from backend.auth.sessions import AuthUnavailable, SessionUser
from backend.deps import AppContext, current_user, get_ctx
from backend.errors import ApiError
from backend.routers.posts import BOARD_OWNER, _LOST_ID, _POST_ID, _viewer
from backend.routers.posts import KIND as POST_KIND
from backend.schemas.api import CommentBody
from backend.tools.lost_animal_api import LostAnimalApiError, mask_contacts

router = APIRouter(tags=["comments"])

KIND = "comment"
MAX_COMMENTS_PER_POST = 200  # 게시글 하나에 보여 주고 받을 수 있는 댓글 수
COMMENT_LIMIT_PER_MINUTE = 5  # 사용자별 1분 작성 횟수
_COMMENT_ID = re.compile(r"^[0-9a-f]{32}$")


def comment_owner(target_id: str) -> str:
    """게시글별 댓글 묶음의 소유자 키. 사용자 키(64자 해시)·게시판 키('board')와 겹치지 않는다."""
    return f"comment:{target_id}"


def _check_target_id(target_id: str) -> None:
    if not (_POST_ID.match(target_id) or _LOST_ID.match(target_id)):
        raise ApiError(404, "post_not_found", "게시글을 찾을 수 없습니다.")


async def _ensure_target(ctx: AppContext, target_id: str) -> str:
    """작성 전에 게시글이 실제로 있는지 확인한다. 반환: 'member' 또는 'lost_api'."""
    _check_target_id(target_id)
    if _POST_ID.match(target_id):
        if not await ctx.store.get(BOARD_OWNER, POST_KIND, target_id):
            raise ApiError(404, "post_not_found", "게시글을 찾을 수 없습니다.")
        return "member"
    if ctx.lost is None:
        raise ApiError(404, "post_not_found", "게시글을 찾을 수 없습니다.")
    try:
        item = await ctx.lost.get(target_id)
    except LostAnimalApiError as exc:
        raise ApiError(502, exc.code, "공공데이터 분실 신고를 확인하지 못했어요. 잠시 후 다시 시도해 주세요.")
    if not item:
        raise ApiError(404, "post_not_found", "게시글을 찾을 수 없습니다.")
    return "lost_api"


def _public(comment_id: str, data: dict, viewer: str | None) -> dict:
    return {
        "id": comment_id,
        "author_name": data.get("author_name") or "회원",
        "body": data["body"],
        "created_at": data["created_at"],
        "mine": viewer is not None and data.get("author") == viewer,
    }


async def _rows(ctx: AppContext, target_id: str) -> list[dict]:
    return await ctx.store.list(comment_owner(target_id), KIND, MAX_COMMENTS_PER_POST)


@router.get("/posts/{target_id}/comments")
async def list_comments(target_id: str, request: Request, ctx: AppContext = Depends(get_ctx)):
    """댓글은 오래된 순으로 돌려준다. 게시글이 사라졌어도 형식이 맞으면 빈 목록이나 남은 댓글을 돌려준다."""
    _check_target_id(target_id)
    rows = await _rows(ctx, target_id)
    viewer = await _viewer(request, ctx)
    items = sorted((_public(r["id"], r["data"], viewer) for r in rows), key=lambda c: (c["created_at"], c["id"]))
    return {"items": items, "count": len(items), "limit": MAX_COMMENTS_PER_POST}


@router.post("/posts/{target_id}/comments", status_code=201)
async def create_comment(
    target_id: str,
    body: CommentBody,
    user: SessionUser = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
):
    text = mask_contacts(body.body).strip()
    if not text:
        raise ApiError(422, "invalid_request", "댓글 내용을 입력해 주세요.")
    try:
        limited = await ctx.sessions.hit_rate_limit(f"comment:{user.owner}", COMMENT_LIMIT_PER_MINUTE, 60)
    except AuthUnavailable:
        raise ApiError(503, "auth_unavailable", "로그인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if limited:
        raise ApiError(429, "comment_rate_limited", "댓글을 너무 자주 쓰고 있어요. 잠시 후 다시 시도해 주세요.")
    source = await _ensure_target(ctx, target_id)
    if len(await _rows(ctx, target_id)) >= MAX_COMMENTS_PER_POST:
        raise ApiError(429, "comment_limit", f"이 게시글에는 댓글을 {MAX_COMMENTS_PER_POST}개까지 달 수 있어요.")
    comment_id = uuid.uuid4().hex
    data = {
        "body": text,
        "author": user.owner,
        "author_name": user.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target_source": source,
    }
    await ctx.store.put(comment_owner(target_id), KIND, comment_id, data)
    return _public(comment_id, data, user.owner)


@router.delete("/posts/{target_id}/comments/{comment_id}", status_code=204)
async def delete_comment(
    target_id: str,
    comment_id: str,
    user: SessionUser = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
):
    _check_target_id(target_id)
    if not _COMMENT_ID.match(comment_id):
        raise ApiError(404, "comment_not_found", "댓글을 찾을 수 없습니다.")
    data = await ctx.store.get(comment_owner(target_id), KIND, comment_id)
    if not data:
        raise ApiError(404, "comment_not_found", "댓글을 찾을 수 없습니다.")
    if data.get("author") != user.owner:
        raise ApiError(403, "comment_forbidden", "내가 쓴 댓글만 지울 수 있어요.")
    await ctx.store.delete(comment_owner(target_id), KIND, comment_id)


async def delete_all_comments(ctx: AppContext, target_id: str) -> int:
    """회원 글을 지울 때 그 글의 댓글도 함께 지운다. 지운 개수를 돌려준다."""
    rows = await _rows(ctx, target_id)
    for r in rows:
        await ctx.store.delete(comment_owner(target_id), KIND, r["id"])
    return len(rows)
