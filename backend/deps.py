from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from fastapi import Request

from backend.auth.sessions import AuthUnavailable, SessionStore, SessionUser
from backend.config import Settings
from backend.errors import ApiError
from backend.storage import Store

COOKIE_NAME = "meet_again_session"
log = logging.getLogger("dasimanna")


@dataclass
class AppContext:
    settings: Settings
    store: Store
    sessions: SessionStore
    animal: Any
    kakao: Any
    llm: Any
    photo_llm: Any = None
    embedder: Any = None
    search_cache: Any = None

    async def aclose(self) -> None:
        # SearchCache uses the Redis client owned by SessionStore; close it only once.
        resources = (self.store, self.sessions, self.animal, self.kakao, self.llm, self.photo_llm, self.embedder)
        closed: set[int] = set()
        for resource in resources:
            if resource is None or id(resource) in closed:
                continue
            closed.add(id(resource))
            close = getattr(resource, "aclose", None)
            if close is None:
                continue
            try:
                await close()
            except Exception:
                log.exception("failed to close backend resource type=%s", type(resource).__name__)


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


async def current_user(request: Request) -> SessionUser:
    ctx: AppContext = request.app.state.ctx
    try:
        user = await ctx.sessions.get(request.cookies.get(COOKIE_NAME))
    except AuthUnavailable:
        raise ApiError(503, "auth_unavailable", "로그인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if user is None:
        raise ApiError(401, "not_authenticated", "로그인이 필요합니다.")
    return user
