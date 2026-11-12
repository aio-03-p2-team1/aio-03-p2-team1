"""인증 API: /auth/register · /auth/login · /auth/me · /auth/logout (10장)."""

from __future__ import annotations

from datetime import datetime, timezone

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Request, Response
from pwdlib import PasswordHash
from pydantic import BaseModel, Field

from backend.auth.sessions import AuthUnavailable, SessionUser, owner_key
from backend.deps import COOKIE_NAME, AppContext, current_user, get_ctx
from backend.errors import ApiError

router = APIRouter(prefix="/auth", tags=["auth"])
hasher = PasswordHash.recommended()  # Argon2

INVALID_LOGIN = "이메일 또는 비밀번호가 올바르지 않습니다."
LOGIN_LIMIT = 10
LOGIN_WINDOW_SECONDS = 600


class RegisterBody(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    name: str
    email: str


def _normalize_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise ApiError(422, "invalid_email", "이메일 형식을 확인해 주세요.")


def _set_cookie(response: Response, ctx: AppContext, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=ctx.settings.auth_session_ttl_seconds,
        httponly=True,
        secure=ctx.settings.cookie_secure,
        samesite=ctx.settings.auth_cookie_samesite,
        path="/api/v1",
    )


def _unavailable() -> ApiError:
    return ApiError(503, "auth_unavailable", "로그인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")


async def _start_session(request: Request, response: Response, ctx: AppContext, user: SessionUser) -> None:
    # 로그인할 때 세션을 회전: 기존 쿠키의 세션은 폐기한다.
    await ctx.sessions.revoke(request.cookies.get(COOKIE_NAME))
    token = await ctx.sessions.create(user)
    _set_cookie(response, ctx, token)


@router.post("/register", response_model=UserOut, status_code=201)
async def register(body: RegisterBody, request: Request, response: Response, ctx: AppContext = Depends(get_ctx)):
    email = _normalize_email(body.email)
    name = body.name.strip()
    if not name:
        raise ApiError(422, "invalid_name", "이름을 입력해 주세요.")
    owner = owner_key(email)
    created = await ctx.store.create(
        owner,
        "identity",
        "account",
        {
            "email": email,
            "name": name,
            "password_hash": hasher.hash(body.password),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if not created:
        raise ApiError(409, "email_taken", "이미 가입한 이메일입니다. 로그인해 주세요.")
    try:
        await _start_session(request, response, ctx, SessionUser(owner=owner, email=email, name=name))
    except AuthUnavailable:
        raise _unavailable()
    return UserOut(name=name, email=email)


@router.post("/login", response_model=UserOut)
async def login(body: LoginBody, request: Request, response: Response, ctx: AppContext = Depends(get_ctx)):
    raw_email = body.email.strip().lower()
    client = request.client.host if request.client else "unknown"
    try:
        limited = await ctx.sessions.hit_rate_limit(f"login:{raw_email}:{client}", LOGIN_LIMIT, LOGIN_WINDOW_SECONDS)
    except AuthUnavailable:
        raise _unavailable()
    if limited:
        raise ApiError(429, "login_rate_limited", "로그인 시도가 너무 많습니다. 10분 후 다시 시도해 주세요.")
    try:
        email = _normalize_email(raw_email)
    except ApiError:
        raise ApiError(401, "invalid_credentials", INVALID_LOGIN)
    owner = owner_key(email)
    account = await ctx.store.get(owner, "identity", "account")
    # 이메일 존재 여부와 관계없이 같은 메시지 (10장)
    if not account or not hasher.verify(body.password, account["password_hash"]):
        raise ApiError(401, "invalid_credentials", INVALID_LOGIN)
    try:
        await _start_session(
            request, response, ctx, SessionUser(owner=owner, email=account["email"], name=account["name"])
        )
    except AuthUnavailable:
        raise _unavailable()
    return UserOut(name=account["name"], email=account["email"])


@router.get("/me", response_model=UserOut)
async def me(user: SessionUser = Depends(current_user)):
    return UserOut(name=user.name, email=user.email)


@router.post("/logout", status_code=204)
async def logout(request: Request, ctx: AppContext = Depends(get_ctx)):
    try:
        await ctx.sessions.revoke(request.cookies.get(COOKIE_NAME))
    except AuthUnavailable:
        raise _unavailable()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/api/v1")
    return response
