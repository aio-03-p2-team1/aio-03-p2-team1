"""FastAPI 앱 진입점: uvicorn backend.main:app"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import Settings, get_settings
from backend.deps import AppContext
from backend.errors import ApiError
from backend.routers import auth, memory, public, searches
from backend.storage import StorageError

log = logging.getLogger("dasimanna")
API_PREFIX = "/api/v1"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def build_context(settings: Settings) -> AppContext:
    from redis import asyncio as aioredis

    from backend.agent.llm import FeatureExtractor
    from backend.auth.sessions import SessionStore
    from backend.storage import build_store
    from backend.tools.animal_api import AnimalApi, SampleAnimalApi
    from backend.tools.kakao import KakaoGeocoder

    timeout = settings.request_timeout_seconds
    redis = aioredis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
    animal = (
        AnimalApi(settings.animal_api_base_url, settings.animal_api_key.get_secret_value(), timeout=min(timeout, 30))
        if settings.animal_api_key
        else SampleAnimalApi()
    )
    kakao_key = settings.kakao_rest_api_key.get_secret_value() if settings.kakao_rest_api_key else None
    llm = (
        FeatureExtractor(settings.openai_api_key.get_secret_value(), settings.openai_model, timeout=timeout)
        if settings.app_mode == "live" and settings.openai_api_key
        else None
    )
    photo_llm = llm or (
        FeatureExtractor(settings.openai_api_key.get_secret_value(), settings.openai_model, timeout=timeout)
        if settings.openai_api_key
        else None
    )
    return AppContext(
        settings=settings,
        store=build_store(settings),
        sessions=SessionStore(redis, settings.auth_session_ttl_seconds),
        animal=animal,
        kakao=KakaoGeocoder(kakao_key, timeout=min(timeout, 15)),
        llm=llm,
        photo_llm=photo_llm,
    )


def create_app(ctx: AppContext | None = None) -> FastAPI:
    settings = ctx.settings if ctx else get_settings()  # live 필수 값 누락 시 여기서 멈춘다

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "ctx", None) is None:
            app.state.ctx = build_context(settings)
        log.info(
            "started mode=%s storage=%s animal_data_source=%s",
            settings.app_mode,
            settings.storage_backend,
            settings.animal_data_source,
        )
        yield

    app = FastAPI(title="다시 만나 API", version="0.1.0", lifespan=lifespan, docs_url=API_PREFIX + "/docs", openapi_url=API_PREFIX + "/openapi.json")
    app.state.ctx = ctx
    allowed = set(settings.cors_origin_list)

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.method in UNSAFE_METHODS and request.url.path.startswith(API_PREFIX):
            origin = request.headers.get("origin")
            if origin is not None and origin.rstrip("/") not in allowed:
                response = JSONResponse(
                    status_code=403,
                    content={"detail": {"code": "origin_not_allowed", "message": "허용되지 않은 출처의 요청입니다."}},
                )
                response.headers["Cache-Control"] = "no-store"
                return response
        response = await call_next(request)
        if request.url.path.startswith(API_PREFIX):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # 422 응답에 비밀번호 등 원본 입력을 담지 않는다.
        fields = [{"loc": [str(p) for p in e.get("loc", [])], "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "invalid_request", "message": "입력값을 확인해 주세요.", "fields": fields}},
        )

    @app.exception_handler(StorageError)
    async def storage_error(request: Request, exc: StorageError):
        log.warning("storage error code=%s status=%s", exc.code, exc.status)
        return JSONResponse(
            status_code=503,
            content={"detail": {"code": exc.code, "message": "데이터 저장소에 연결하지 못했습니다."}},
        )

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    for router in (public.router, auth.router, searches.router, memory.router):
        app.include_router(router, prefix=API_PREFIX)
    return app


_app: FastAPI | None = None


def __getattr__(name):  # pragma: no cover - uvicorn 진입점
    """`backend.main:app` 을 처음 읽을 때 앱을 만든다.

    테스트가 모듈을 import 할 때 .env 설정 검증이 먼저 일어나지 않게 하기 위함이다.
    """
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
