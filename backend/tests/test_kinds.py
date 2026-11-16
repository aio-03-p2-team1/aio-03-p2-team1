import asyncio
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import fakeredis
import pytest

from backend.agent.breed import BreedNormalizer
from backend.tests.conftest import make_settings
from backend.tools.kinds import KindRepository
from scripts.init_kinds_sqlite import SqliteSink
from scripts.kind_sync import normalize_record


def run_async(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


@pytest.fixture
def repository(tmp_path):
    path = str(tmp_path / 'kinds.db')
    sink = SqliteSink(path)
    sink.sync([normalize_record('dog', {'kind_cd': '1', 'KNm': '푸들'}, 'now'),
               normalize_record('cat', {'kind_cd': '2', 'KNm': '코리안 숏헤어'}, 'now')])
    sink.close()
    return KindRepository(make_settings(sqlite_path=path), fakeredis.FakeAsyncRedis())


@run_async
async def test_lookup_is_scoped_cached_and_partial(repository):
    assert [r['name'] for r in await repository.lookup('dog', '푸')] == ['푸들']
    assert await repository.lookup('cat', '푸') == []
    assert await repository.redis.ttl('meet-again:kinds:dog') > 86390
    repository._rows = AsyncMock(side_effect=AssertionError('cache miss'))
    assert len(await repository.lookup('dog')) == 1


@run_async
async def test_rules_alias_and_description(repository):
    client = SimpleNamespace(bind_tools=lambda *a, **k: pytest.fail('rules should win'))
    agent = BreedNormalizer(repository, client)
    assert (await agent.resolve('cat', '코숏'))['kind_code'] == '2'
    assert await agent.resolve('dog', '') is None
    assert await BreedNormalizer(repository).resolve('dog', '없는품종') is None


@run_async
async def test_ai_code_must_have_been_seen_in_tool(repository):
    client = SimpleNamespace(bind_tools=lambda *a, **k: SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(tool_calls=[], content='1'))))
    assert await BreedNormalizer(repository, client).resolve('dog', '애매한품종') is None


@run_async
async def test_ai_uses_lookup_then_validates_code(repository):
    calls = [SimpleNamespace(tool_calls=[{'name': 'lookup_kinds', 'args': {'species': 'dog', 'name': '푸'}, 'id': 'call1'}], content=''),
             SimpleNamespace(tool_calls=[], content='1')]
    client = SimpleNamespace(bind_tools=lambda *a, **k: SimpleNamespace(ainvoke=AsyncMock(side_effect=calls)))
    assert (await BreedNormalizer(repository, client).resolve('dog', '푸드르'))['kind_code'] == '1'


@run_async
async def test_refresh_invalidates_and_skips_within_seven_days(repository, monkeypatch):
    from contextlib import asynccontextmanager
    from scripts import refresh_kinds

    @asynccontextmanager
    async def lock(*args, **kwargs):
        yield

    monkeypatch.setattr(repository.redis, 'lock', lock)
    fetch = AsyncMock(return_value=[normalize_record('dog', {'kind_cd': '1', 'KNm': '푸들'}, 'now')])
    monkeypatch.setattr(refresh_kinds, 'fetch_records', fetch)
    await repository.lookup('dog')
    assert await refresh_kinds.refresh(repository.settings, repository.redis)
    assert await repository.redis.get('meet-again:kinds:dog') is None
    assert not await refresh_kinds.refresh(repository.settings, repository.redis)
    assert fetch.await_count == 1


def test_species_change_and_explicit_clear_do_not_inherit_breed():
    from backend.agent.criteria import merge_conditions
    prior = {'species': 'dog', 'breed': '푸들'}
    assert not merge_conditions({'species': 'cat'}, prior, None)[0]['breed']
    assert not merge_conditions({'species': 'dog', 'breed': ''}, prior, {'breed': '푸들'})[0]['breed']


def test_public_api_validates_species_and_returns_rows(repository):
    from fastapi.testclient import TestClient
    from backend.main import create_app
    from backend.tests.conftest import build_ctx
    ctx = build_ctx()
    ctx.kinds = repository
    client = TestClient(create_app(ctx))
    assert client.get('/api/v1/kinds?species=bad').status_code == 422
    result = client.get('/api/v1/kinds?species=dog&name=푸')
    assert result.status_code == 200
    assert result.json()['kinds'] == [{'kind_code': '1', 'name': '푸들', 'species': 'dog'}]


@run_async
async def test_database_like_is_scoped_and_escapes_wildcards(repository):
    assert [r['kind_code'] for r in await repository.lookup_db('dog', '푸')] == ['1']
    assert await repository.lookup_db('cat', '푸') == []
    assert await repository.lookup_db('dog', '%') == []
    assert await repository.lookup_db('dog', "' OR 1=1 --") == []
    assert [r['kind_code'] for r in await repository.lookup_db('cat', '코리안숏')] == ['2']


@run_async
async def test_supabase_like_and_pagination():
    import httpx
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.params['species'] == 'eq.other'
        assert request.url.params['search_name'] == 'like.%토끼%'
        if request.url.params['offset'] == '0':
            return httpx.Response(200, json=[{'kind_code': str(i), 'name': '토끼', 'species': 'other', 'kind_aliases': []}
                                           for i in range(1000)])
        return httpx.Response(200, json=[{'kind_code': 'last', 'name': '토끼', 'species': 'other', 'kind_aliases': []}])

    repository = KindRepository(make_settings(storage_backend='supabase', supabase_service_role_key='test-only'),
                                transport=httpx.MockTransport(handler))
    result = await repository.lookup_db('etc', '토 끼')
    assert len(result) == 1001
    assert result[-1]['species'] == 'etc'
    assert requests[-1].url.params['offset'] == '1000'


@run_async
async def test_refresh_retries_database_write(repository, monkeypatch):
    from contextlib import asynccontextmanager
    from scripts import refresh_kinds, init_kinds_sqlite

    @asynccontextmanager
    async def lock(*args, **kwargs):
        yield

    monkeypatch.setattr(repository.redis, 'lock', lock)
    monkeypatch.setattr(refresh_kinds, 'fetch_records', AsyncMock(return_value=[{'kind_code': '1'}]))
    sink = SimpleNamespace(sync=Mock(side_effect=[RuntimeError(), None]),
                           close=lambda: None)
    monkeypatch.setattr(init_kinds_sqlite, 'SqliteSink', lambda path: sink)
    sleep = AsyncMock()
    monkeypatch.setattr(refresh_kinds.asyncio, 'sleep', sleep)
    assert await refresh_kinds.refresh(repository.settings, repository.redis)
    assert sink.sync.call_count == 2
    sleep.assert_awaited_once_with(0.5)


def test_graph_normalizes_breed_between_context_and_plan(repository):
    from backend.tests.test_graph import deps, search, START
    d = deps()
    d['breed_normalizer'] = BreedNormalizer(repository)
    result = search(d, {'species': 'cat', 'region': '전체', 'lost_date': START, 'breed': '코숏'})
    assert result['status'] == 'completed'
    assert result['criteria']['breed'] == '코리안 숏헤어'
    assert result['criteria']['breed_code'] == '2'
    assert result['trace'].index('context') < result['trace'].index('breed') < result['trace'].index('plan')


def test_graph_finishes_with_error_when_breed_database_fails(repository):
    from backend.tests.test_graph import deps, search, START
    from backend.storage import StorageError
    d = deps()
    repository.rows = AsyncMock(side_effect=StorageError('kinds_unavailable'))
    d['breed_normalizer'] = BreedNormalizer(repository)
    result = search(d, {'species': 'dog', 'region': '전체', 'lost_date': START, 'breed': '푸들'})
    assert result['status'] == 'failed'
    assert result['error']['code'] == 'breed_normalization_failed'
    assert 'execute' not in result['trace']


@run_async
async def test_startup_catalog_contains_only_codes_and_names_and_is_lru_cached(repository):
    await repository.load_catalog()
    assert repository.catalog() == (('1', '푸들'), ('2', '코리안 숏헤어'))
    assert repository.catalog.cache_info().maxsize == 1
    repository._rows = AsyncMock(side_effect=AssertionError('runtime DB read'))
    first = repository.catalog()
    assert repository.catalog() is first
    assert repository.catalog.cache_info().hits >= 2


def test_description_no_longer_extracts_breed(repository):
    from backend.tests.test_graph import deps, search, START
    d = deps()
    repository.rows = AsyncMock(side_effect=AssertionError('description must not query breeds'))
    d['breed_normalizer'] = BreedNormalizer(repository)
    result = search(d, {'species': 'dog', 'region': '전체', 'lost_date': START, 'description': '갈색 푸들입니다'})
    assert result['status'] == 'completed'
    assert not result['criteria'].get('breed')
    assert result['criteria']['breed_code'] is None
    repository.rows.assert_not_awaited()


def test_lifespan_warms_catalog_before_requests(repository):
    from fastapi.testclient import TestClient
    from backend.main import create_app
    from backend.tests.conftest import build_ctx
    ctx = build_ctx()
    ctx.kinds = repository
    assert repository.catalog() == ()
    with TestClient(create_app(ctx)):
        assert repository.catalog() == (('1', '푸들'), ('2', '코리안 숏헤어'))


def test_search_accepts_code_and_uses_server_name_without_ai(repository):
    from backend.schemas.api import SearchBody
    from backend.tests.test_graph import deps, search, START
    d = deps()
    d['breed_normalizer'] = BreedNormalizer(repository, SimpleNamespace(
        bind_tools=lambda *a, **k: pytest.fail('code must not invoke AI')))
    body = SearchBody.model_validate({'criteria': {
        'species': 'cat', 'region': '전체', 'lost_date': START, 'breed_code': '2', 'breed': '위조 이름'}})
    result = search(d, body.criteria.model_dump(exclude_none=True))
    assert result['status'] == 'completed'
    assert result['criteria']['breed_code'] == '2'
    assert result['criteria']['breed'] == '코리안 숏헤어'


@pytest.mark.parametrize('species,code', [('dog', 'unknown'), ('dog', '2'), ('all', '1')])
def test_search_rejects_unknown_or_wrong_species_code(repository, species, code):
    from backend.tests.test_graph import deps, search, START
    d = deps()
    d['breed_normalizer'] = BreedNormalizer(repository)
    result = search(d, {'species': species, 'region': '전체', 'lost_date': START, 'breed_code': code})
    assert result['status'] == 'failed'
    assert result['error']['code'] == 'invalid_breed_code'
    assert 'execute' not in result['trace']


def test_clearing_or_changing_species_clears_session_code_and_name():
    from backend.agent.criteria import merge_conditions
    prior = {'species': 'dog', 'breed_code': '1', 'breed': '푸들'}
    for current in ({'species': 'dog', 'breed_code': ''}, {'species': 'cat'}):
        merged, _ = merge_conditions(current, prior, prior)
        assert merged['breed_code'] == merged['breed'] == ''
