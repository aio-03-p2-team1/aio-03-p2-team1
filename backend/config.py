"""환경변수 설정.

- pydantic-settings로 검증한다.
- live 모드에서 필수 값이 비어 있으면 시작 단계에서 누락 항목 *이름만* 알리고 멈춘다.
- 비밀 값은 repr/로그에 노출하지 않는다(SecretStr).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """설정 누락·형식 오류. 메시지에는 변수 이름만 담는다."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_mode: Literal["local", "live"] = "local"
    storage_backend: Literal["sqlite", "supabase"] = "sqlite"
    sqlite_path: str = ".data/meet-again.db"

    supabase_url: str = "https://yaywavgjaquftvekuvsb.supabase.co"
    supabase_schema: str = "aio-03-p2-team1-demo"
    supabase_service_role_key: SecretStr | None = None

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-6-luna"

    # ANIMAL_API_KEY 우선, 별칭 ANIMAL_API_SERVICE_KEY 지원.
    animal_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANIMAL_API_KEY", "ANIMAL_API_SERVICE_KEY")
    )
    animal_api_base_url: str = "https://apis.data.go.kr/1543061/abandonmentPublicService_v2"

    kakao_rest_api_key: SecretStr | None = None

    discord_bot_token: SecretStr | None = None
    discord_allowed_user_ids: str = ""

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    redis_url: str = "redis://127.0.0.1:6380/0"

    auth_session_ttl_seconds: int = Field(default=86400, ge=300, le=60 * 60 * 24 * 30)
    auth_cookie_secure: bool | None = None
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # 이전 배포 설정 호환용. 맞춤 검색은 요구사항에 따라 1,000건 1페이지로 고정한다.
    max_search_pages: int = Field(default=1, ge=1, le=10)
    max_reflections: int = Field(default=2, ge=0, le=3)
    max_tool_calls: int = Field(default=30, ge=10, le=60)
    request_timeout_seconds: int = Field(default=60, ge=10, le=120)

    @field_validator(
        "supabase_service_role_key",
        "openai_api_key",
        "animal_api_key",
        "kakao_rest_api_key",
        "discord_bot_token",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("animal_api_base_url")
    @classmethod
    def _force_https(cls, value: str) -> str:
        # 포털 예시의 http:// 를 HTTPS로 보정.
        value = value.strip().rstrip("/")
        if value.startswith("http://"):
            value = "https://" + value[len("http://") :]
        return value

    @field_validator("redis_url")
    @classmethod
    def _check_redis_url(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("redis://", "rediss://", "unix://")):
            # CIDR 등이 아닌 Redis 접속 URL을 받아야 한다. 값은 출력하지 않는다.
            raise ValueError("REDIS_URL은 redis:// · rediss:// · unix:// 형식의 접속 URL이어야 합니다")
        return value

    @model_validator(mode="after")
    def _check_live(self) -> "Settings":
        if self.auth_cookie_samesite == "none" and self.cookie_secure is False:
            raise ConfigError("AUTH_COOKIE_SAMESITE=none 이면 AUTH_COOKIE_SECURE=true 가 필요합니다")
        if self.storage_backend == "supabase" and self.supabase_service_role_key is None:
            raise ConfigError("설정 누락: SUPABASE_SERVICE_ROLE_KEY")
        if self.app_mode == "live":
            missing = []
            if self.storage_backend != "supabase":
                missing.append("STORAGE_BACKEND=supabase")
            if self.openai_api_key is None:
                missing.append("OPENAI_API_KEY")
            if self.animal_api_key is None:
                missing.append("ANIMAL_API_KEY")
            if missing:
                raise ConfigError("실제 연동 모드 설정 누락: " + ", ".join(missing))
        return self

    @property
    def cookie_secure(self) -> bool:
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return self.app_mode == "live"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def animal_data_source(self) -> Literal["api", "sample"]:
        """코드가 계산하는 값이며 환경변수로 설정하지 않는다."""
        return "api" if self.animal_api_key is not None else "sample"


@lru_cache
def get_settings() -> Settings:
    return Settings()
