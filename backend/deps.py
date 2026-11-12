"""요청 공용 의존성: 앱 컨텍스트와 로그인 사용자."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from backend.auth.sessions import AuthUnavailable, SessionStore, SessionUser
from backend.config import Settings
from backend.errors import ApiError
from backend.storage import Store

COOKIE_NAME = "meet_again_session"


@dataclass
class AppContext:
    settings: Settings
    store: Store
    sessions: SessionStore
    animal: Any  # backend.tools.animal_api.AnimalApi
    kakao: Any  # backend.tools.kakao.KakaoGeocoder
    llm: Any  # backend.agent.llm.FeatureExtractor | None


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
