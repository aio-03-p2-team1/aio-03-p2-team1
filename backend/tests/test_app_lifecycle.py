import asyncio
import sqlite3

import pytest

from backend.config import Settings
from backend.deps import AppContext
from backend.main import create_app
from backend.storage.sqlite import SqliteStore


class ClosingResource:
    def __init__(self, **attrs):
        self.close_count = 0
        for name, value in attrs.items():
            setattr(self, name, value)

    async def aclose(self):
        self.close_count += 1


def test_app_lifespan_closes_context_resources_once():
    store = SqliteStore(":memory:")
    sessions = ClosingResource()
    animal = ClosingResource(source="sample")
    kakao = ClosingResource(configured=False)
    llm = ClosingResource()
    embedder = ClosingResource()
    cache = ClosingResource()
    ctx = AppContext(
        settings=Settings(_env_file=None),
        store=store,
        sessions=sessions,
        animal=animal,
        kakao=kakao,
        llm=llm,
        photo_llm=llm,
        embedder=embedder,
        search_cache=cache,
    )

    app = create_app(ctx)

    async def run_lifespan():
        async with app.router.lifespan_context(app):
            assert app.state.ctx is ctx

    asyncio.run(run_lifespan())

    assert [resource.close_count for resource in (sessions, animal, kakao, llm, embedder)] == [1] * 5
    with pytest.raises(sqlite3.ProgrammingError):
        store._conn.execute("SELECT 1")
    # SearchCache shares its Redis client with SessionStore and must not close it independently.
    assert cache.close_count == 0
