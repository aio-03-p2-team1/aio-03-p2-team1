"""Owner-scoped, short-lived results for single-call text/photo refinement."""

from __future__ import annotations

import hashlib
import json
import uuid

REFINEMENT_TTL_SECONDS = 3600
LOCK_TTL_SECONDS = 180


def _lock_key(owner: str, source_hash: str) -> str:
    return f"text-refine-lock:{owner}:{source_hash}"


def _result_key(owner: str, refinement_id: str) -> str:
    return f"text-refine:{owner}:{refinement_id}"


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def begin(redis, owner: str, text: str, token: str) -> bool:
    return bool(await redis.set(_lock_key(owner, source_hash(text)), token, ex=LOCK_TTL_SECONDS, nx=True))


async def finish(redis, owner: str, text: str, token: str) -> None:
    key = _lock_key(owner, source_hash(text))
    # Compare-and-delete so an expired lock replaced by another request is not removed.
    try:
        await redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            1, key, token,
        )
    except Exception:
        # Some lightweight Redis-compatible test doubles do not implement Lua.
        current = await redis.get(key)
        if current in (token, token.encode()):
            await redis.delete(key)


async def save(redis, owner: str, result: dict) -> str:
    refinement_id = uuid.uuid4().hex
    await redis.set(
        _result_key(owner, refinement_id),
        json.dumps(result, ensure_ascii=False),
        ex=REFINEMENT_TTL_SECONDS,
    )
    return refinement_id


async def load(redis, owner: str, refinement_id: str | None) -> dict | None:
    if not refinement_id or len(refinement_id) != 32:
        return None
    raw = await redis.get(_result_key(owner, refinement_id))
    if not raw:
        return None
    return json.loads(raw)
