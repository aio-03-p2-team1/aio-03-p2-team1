"""Public reference data; never substitute sample breeds on storage failure."""
import asyncio
import json
import sqlite3
from functools import lru_cache

import httpx
from redis.exceptions import RedisError

from backend.storage import StorageError


def normalize(value):
    return ''.join(value.split()).casefold()


class KindRepository:
    def __init__(self, settings, redis=None, transport=None):
        self.settings = settings
        self.redis = redis
        self.transport = transport
        self._catalog_data = ()
        self.catalog = lru_cache(maxsize=1)(lambda: self._catalog_data)

    async def load_catalog(self):
        """Warm the process-local code/name-only snapshot at server startup."""
        pairs = {}
        for species in ('dog', 'cat', 'etc'):
            for row in await self._rows(species):
                pairs[row['kind_code']] = row['name']
        self._catalog_data = tuple(sorted(pairs.items()))
        self.catalog.cache_clear()
        self.catalog()


    async def _rows(self, species, name=""):
        query = normalize(name)
        pattern = "%" + query.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        species = 'other' if species == 'etc' else species
        try:
            if self.settings.storage_backend == 'sqlite':
                def read():
                    with sqlite3.connect(self.settings.sqlite_path) as db:
                        db.row_factory = sqlite3.Row
                        return [dict(r) for r in db.execute(
                            'SELECT k.kind_code,k.name,k.species,a.alias FROM kinds k LEFT JOIN kind_aliases a '
                            "ON a.kind_code=k.kind_code WHERE k.active=1 AND k.species=? AND k.search_name LIKE ? ESCAPE '!' ORDER BY k.name", (species, pattern))]
                return await asyncio.to_thread(read)
            key = self.settings.supabase_service_role_key.get_secret_value()
            headers = {'apikey': key, 'Authorization': f'Bearer {key}', 'Accept-Profile': self.settings.supabase_schema}
            rows = []
            async with httpx.AsyncClient(headers=headers, timeout=30, transport=self.transport) as client:
                offset = 0
                while True:
                    response = await client.get(self.settings.supabase_url.rstrip('/') + '/rest/v1/kinds', params={
                        'select': 'kind_code,name,species,kind_aliases(alias)', 'active': 'eq.true',
                        'species': f'eq.{species}', 'search_name': 'like.%' + query.replace(chr(92), chr(92) * 2).replace('%', chr(92) + '%').replace('_', chr(92) + '_') + '%',
                        'order': 'kind_code', 'offset': offset, 'limit': 1000})
                    response.raise_for_status()
                    page = response.json()
                    for row in page:
                        aliases = row.pop('kind_aliases', [])
                        rows.extend([{**row, 'alias': a['alias']} for a in aliases] or [{**row, 'alias': None}])
                    if len(page) < 1000:
                        break
                    offset += len(page)
            return rows
        except (sqlite3.Error, httpx.HTTPError, ValueError) as exc:
            raise StorageError('kinds_unavailable') from exc

    async def rows(self, species):
        cache_key = f'meet-again:kinds:{species}'
        if self.redis is not None:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    return json.loads(cached)
            except (RedisError, OSError, ValueError):
                pass
        rows = await self._rows(species)
        if self.redis is not None:
            try:
                await self.redis.set(cache_key, json.dumps(rows), ex=86400)
            except (RedisError, OSError):
                pass
        return rows

    @staticmethod
    def _public_rows(rows):
        return list({r['kind_code']: {'kind_code': r['kind_code'], 'name': r['name'],
                                    'species': 'etc' if r['species'] == 'other' else r['species']}
                     for r in rows}.values())

    async def lookup_db(self, species: str, name: str = '') -> list[dict]:
        """AI tool: execute a scoped LIKE query against the source database."""
        return self._public_rows(await self._rows(species, name))

    async def lookup(self, species: str, name: str = '') -> list[dict]:
        """Public cached list; filter with the same literal LIKE substring semantics."""
        query = normalize(name)
        rows = await self.rows(species)
        return self._public_rows(r for r in rows if query in normalize(r['name']))
