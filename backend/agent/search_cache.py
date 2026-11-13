import asyncio
import hashlib
import json
import secrets
import time
from contextlib import asynccontextmanager

from redis.exceptions import RedisError

from backend.errors import ApiError

TTL = 600
VERSION = "rrf-v1"


def condition_key(owner, criteria, *, source, model, reflection=True):
    payload = {"owner": owner, "criteria": criteria, "source": source, "model": model,
               "reflection": reflection, "version": VERSION}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return "meet-again:search:" + digest


class SearchCache:
    def __init__(self, redis):
        self.redis = redis

    async def get(self, key):
        try:
            value = await self.redis.get(key)
            if not value:
                return None
            result = json.loads(value)
            if not isinstance(result, dict):
                raise ValueError("snapshot")
            return result
        except (RedisError, OSError, ValueError, TypeError) as exc:
            raise ApiError(503, "search_cache_unavailable", "검색 캐시에 연결하지 못했습니다.") from exc

    async def put(self, key, value):
        try:
            await self.redis.set(key, json.dumps(value, ensure_ascii=False, allow_nan=False), ex=TTL)
        except (RedisError, OSError) as exc:
            raise ApiError(503, "search_cache_unavailable", "검색 결과를 캐시에 저장하지 못했습니다.") from exc

    @asynccontextmanager
    async def lock(self, key):
        lock_key, token = key + ":lock", secrets.token_hex(16)
        deadline = time.monotonic() + 125
        acquired = False
        try:
            while not acquired:
                acquired = bool(await self.redis.set(lock_key, token, nx=True, ex=150))
                if not acquired:
                    if time.monotonic() >= deadline:
                        raise ApiError(409, "search_in_progress", "같은 조건의 검색이 진행 중입니다. 잠시 후 다시 확인해 주세요.")
                    await asyncio.sleep(0.1)
            yield
        except (RedisError, OSError) as exc:
            raise ApiError(503, "search_cache_unavailable", "검색 캐시에 연결하지 못했습니다.") from exc
        finally:
            if acquired:
                # WATCH로 자신의 잠금만 해제한다. 만료 후 다른 요청의 잠금은 지우지 않는다.
                from redis.exceptions import WatchError
                try:
                    async with self.redis.pipeline(transaction=True) as pipe:
                        await pipe.watch(lock_key)
                        current = await pipe.get(lock_key)
                        if current in (token, token.encode()):
                            pipe.multi()
                            pipe.delete(lock_key)
                            await pipe.execute()
                except (RedisError, OSError, WatchError):
                    pass
