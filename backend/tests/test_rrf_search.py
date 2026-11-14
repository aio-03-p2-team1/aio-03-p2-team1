import asyncio
import fakeredis
import pytest
from fastapi.testclient import TestClient

from backend.agent.embeddings import DIMENSIONS, Embedder
from backend.agent.llm import LlmError
from backend.agent.ranking import feature_text, fuse_rrf
from backend.agent.search_cache import SearchCache, condition_key
from backend.agent.runner import run_search
from backend.main import create_app
from .conftest import ORIGIN, FakeAnimal, FakeEmbedder, api_item, build_ctx, signup
from .test_graph import START, deps

CRITERIA = {"species": "dog", "region": "전체", "lost_date": START, "description": "갈색 푸들"}


def test_rrf_combines_rank_positions_not_raw_score_scales():
    items = [{"id": str(i), "score": 9999 - i} for i in range(3)]
    result = fuse_rrf(items, {"0": 0.1, "1": 0.5, "2": 0.9})
    assert result[0]["score"] == pytest.approx(1 / 61 + 1 / 63)
    assert [item["rank"] for item in result] == [1, 2, 3]
    assert result[0]["lexical_score"] == 9999
    assert "secret" not in feature_text({"breed": "푸들", "id": "secret", "care": {"tel": "secret"}})


def test_hash_order_owner_and_model_scope():
    args = dict(source="api", model="model")
    assert condition_key("a", {"a": 1, "b": 2}, **args) == condition_key("a", {"b": 2, "a": 1}, **args)
    assert condition_key("a", CRITERIA, **args) != condition_key("b", CRITERIA, **args)
    assert "갈색" not in condition_key("a", CRITERIA, **args)


def test_thousand_embeddings_top_300_cache_hit_ttl_and_expiry():
    async def scenario():
        animal = FakeAnimal(pages=[[api_item(i) for i in range(1005)]])
        d = deps(animal)
        redis = fakeredis.FakeAsyncRedis()
        d["search_cache"] = SearchCache(redis)
        first = await run_search(d, "owner", {"criteria": CRITERIA})
        assert len(first["candidates"]) == 300
        assert first["scope"]["fetched_rows"] == 1000
        assert not first["scope"]["complete"]
        assert animal.calls == [{"region_code": None, "page": 1, "species": "dog", "rows": 1000}]
        assert len(d["embedder"].calls[0]) == 1001
        assert 598 <= await redis.ttl(first["cache_key"]) <= 600
        snapshot = await d["search_cache"].get(first["cache_key"])
        assert len(snapshot["candidates"]) == 300
        assert "raw_items" not in snapshot and "semantic_scores" not in snapshot
        second = await run_search(d, "owner", {"criteria": dict(reversed(list(CRITERIA.items())))})
        assert second["cache_hit"] and second["run_id"] != first["run_id"]
        assert second["candidates"] == first["candidates"]
        assert len(animal.calls) == len(d["embedder"].calls) == 1
        assert second["tool_call_count"] == 0
        alias = await run_search(d, "owner", {"criteria": {**CRITERIA, "species": "개", "region": "all"}})
        assert alias["cache_hit"] and len(animal.calls) == 1
        await redis.expire(first["cache_key"], 0)
        third = await run_search(d, "owner", {"criteria": CRITERIA})
        assert not third["cache_hit"] and len(animal.calls) == 2
        await run_search(d, "another-owner", {"criteria": CRITERIA})
        assert len(animal.calls) == 3
    asyncio.run(scenario())


def test_parallel_cache_miss_only_fetches_once():
    async def scenario():
        d = deps(FakeAnimal(pages=[[api_item(1)]]))
        d["search_cache"] = SearchCache(fakeredis.FakeAsyncRedis())
        results = await asyncio.gather(*(run_search(d, "a", {"criteria": CRITERIA}) for _ in range(3)))
        assert sum(bool(r["cache_hit"]) for r in results) == 2
        assert len(d["animal"].calls) == 1
    asyncio.run(scenario())


def test_embedding_failure_is_not_cached_or_faked():
    class Broken(FakeEmbedder):
        async def embed(self, texts):
            raise LlmError("llm_quota")

    async def scenario():
        d = deps(FakeAnimal(pages=[[api_item(1)]]))
        d["embedder"] = Broken()
        d["search_cache"] = SearchCache(fakeredis.FakeAsyncRedis())
        first = await run_search(d, "a", {"criteria": CRITERIA})
        assert first["status"] == "failed" and first["error"]["code"] == "llm_quota"
        assert first["candidates"] == []
        assert await d["search_cache"].get(first["cache_key"]) is None
    asyncio.run(scenario())


def test_pagination_detail_and_owner_isolation_without_new_tool_calls():
    ctx = build_ctx(animal=FakeAnimal(pages=[[api_item(i) for i in range(350)]]))
    ctx.search_cache = SearchCache(ctx.sessions._redis)
    with TestClient(create_app(ctx), headers={"Origin": ORIGIN}) as client:
        signup(client)
        first = client.post("/api/v1/searches", json={"criteria": CRITERIA}).json()
        identifier = first["run_id"]
        assert first["pagination"] == {"page": 1, "page_size": 20, "total": 300, "pages": 15}
        second = client.get(f"/api/v1/runs/{identifier}?page=2").json()
        assert len(second["candidates"]) == 20
        assert second["candidates"][0]["rank"] == 21
        assert len(ctx.animal.calls) == len(ctx.embedder.calls) == 1
        candidate = second["candidates"][0]["id"]
        assert client.get(f"/api/v1/runs/{identifier}/candidates/{candidate}").status_code == 200
        assert client.get(f"/api/v1/runs/{identifier}?page=16").status_code == 422
        # TTL 만료 후 같은 조건의 새 스냅샷이 생겨도 이전 실행 이력은 바뀌지 않는다.
        asyncio.run(ctx.search_cache.redis.delete(first["cache_key"]))
        ctx.animal.pages = [[api_item(9999)]]
        client.post("/api/v1/searches", json={"criteria": CRITERIA})
        assert client.get(f"/api/v1/runs/{identifier}?page=2").json()["candidates"] == second["candidates"]
        client.post("/api/v1/auth/logout")
        signup(client, email="second@example.com")
        assert client.get(f"/api/v1/runs/{identifier}?page=2").status_code == 404
        assert client.get(f"/api/v1/runs/{identifier}/candidates/{candidate}").status_code == 404


def test_embedding_client_is_injectable_and_validates_vectors():
    class FakeEmbeddings:
        async def aembed_documents(self, texts):
            return [[float(i + 1)] * DIMENSIONS for i, _ in enumerate(texts)]

    result = asyncio.run(Embedder("test", client=FakeEmbeddings()).embed(["a", "b"]))
    assert result[0][0] == 1 and result[1][0] == 2

    class EmptyEmbeddings:
        async def aembed_documents(self, texts):
            return []

    with pytest.raises(LlmError, match="llm_response"):
        asyncio.run(Embedder("test", client=EmptyEmbeddings()).embed(["a"]))


def test_redis_failure_stops_before_public_api():
    from backend.errors import ApiError

    class BrokenRedis:
        async def get(self, key):
            raise OSError("offline")

    d = deps(FakeAnimal())
    d["search_cache"] = SearchCache(BrokenRedis())
    with pytest.raises(ApiError) as error:
        asyncio.run(run_search(d, "a", {"criteria": CRITERIA}))
    assert error.value.status_code == 503 and not d["animal"].calls


def test_effective_memory_conditions_hit_but_current_origin_is_preserved():
    async def scenario():
        d = deps(FakeAnimal(pages=[[api_item(1)]]))
        d["search_cache"] = SearchCache(fakeredis.FakeAsyncRedis())
        await d["store"].put("a", "memory", "pet", {"confirmed": {"color": "갈색"}})
        first = await run_search(d, "a", {"criteria": CRITERIA, "profile_id": "pet"})
        assert first["memory_used"] == {"color": "갈색"}
        second = await run_search(d, "a", {"criteria": {**CRITERIA, "color": "갈색"}})
        assert second["cache_hit"] and second["memory_used"] == {}
        thread = await d["store"].get("a", "thread", second["thread_id"])
        assert thread["criteria"]["color"] == "갈색"
    asyncio.run(scenario())


def test_real_api_without_embedding_key_does_not_fall_back_to_lexical():
    d = deps(FakeAnimal(pages=[[api_item(1)]]))
    d["embedder"] = None
    result = asyncio.run(run_search(d, "a", {"criteria": CRITERIA}))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "embedding_not_configured"
    assert result["candidates"] == []
