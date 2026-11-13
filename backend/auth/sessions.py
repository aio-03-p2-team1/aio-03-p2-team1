"""Redis 세션과 로그인 호출 제한.

- 키 접두사 meet-again:auth:
- 세션 원문은 32바이트 임의 토큰, Redis 키에는 SHA-256 만 저장
- Redis 장애는 AuthUnavailable 로 올려 503 으로 응답한다(인증 우회 금지)
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass

from redis.exceptions import RedisError

PREFIX = "meet-again:auth:"


class AuthUnavailable(RuntimeError):
    pass


@dataclass
class SessionUser:
    owner: str
    email: str
    name: str


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def owner_key(email: str) -> str:
    """정규화한 이메일의 SHA-256 = 소유자 키."""
    return _digest(email.strip().lower())


class SessionStore:
    def __init__(self, redis, ttl_seconds: int):
        self._redis = redis
        self._ttl = ttl_seconds

    async def create(self, user: SessionUser) -> str:
        token = secrets.token_urlsafe(32)
        payload = json.dumps({"owner": user.owner, "email": user.email, "name": user.name}, ensure_ascii=False)
        try:
            await self._redis.set(PREFIX + "session:" + _digest(token), payload, ex=self._ttl)
        except (RedisError, OSError) as exc:
            raise AuthUnavailable() from exc
        return token

    async def get(self, token: str | None) -> SessionUser | None:
        if not token:
            return None
        try:
            raw = await self._redis.get(PREFIX + "session:" + _digest(token))
        except (RedisError, OSError) as exc:
            raise AuthUnavailable() from exc
        if not raw:
            return None
        data = json.loads(raw)
        return SessionUser(owner=data["owner"], email=data["email"], name=data["name"])

    async def revoke(self, token: str | None) -> None:
        if not token:
            return
        try:
            await self._redis.delete(PREFIX + "session:" + _digest(token))
        except (RedisError, OSError) as exc:
            raise AuthUnavailable() from exc

    async def hit_rate_limit(self, bucket: str, limit: int, window_seconds: int) -> bool:
        """호출 횟수를 1 늘리고, 한도를 넘었으면 True."""
        key = PREFIX + "rate:" + _digest(bucket)
        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, window_seconds)
        except (RedisError, OSError) as exc:
            raise AuthUnavailable() from exc
        return count > limit
