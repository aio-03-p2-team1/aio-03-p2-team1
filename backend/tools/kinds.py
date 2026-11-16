"""Public reference data; never substitute sample breeds on storage failure."""
import asyncio
import json
import sqlite3

import httpx
from redis.exceptions import RedisError

from backend.storage import StorageError


def normalize(value):
    return ''.join(value.split()).casefold()


class KindRepository:
    def __init__(self, settings, redis=None):
        self.settings = settings
        self.redis = redis

    async def _rows(self, species):
        species = 'other' if species == 'etc' else species
        try:
            if self.settings.storage_backend == 'sqlite':
                def read():
                    with sqlite3.connect(self.settings.sqlite_path) as db:
                        db.row_factory = sqlite3.Row
                        return [dict(r) for r in db.execute(
                            'SELECT k.kind_code,k.name,k.species,a.alias FROM kinds k LEFT JOIN kind_aliases a '
                            'ON a.kind_code=k.kind_code WHERE k.active=1 AND k.species=? ORDER BY k.name', (species,))]
                return await asyncio.to_thread(read)
            key = self.settings.supabase_service_role_key.get_secret_value()
            headers = {'apikey': key, 'Authorization': f'Bearer {key}', 'Accept-Profile': self.settings.supabase_schema}
            rows = []
            async with httpx.AsyncClient(headers=headers, timeout=30) as client:
                for offset in range(0, 10000, 1000):
                    response = await client.get(self.settings.supabase_url.rstrip('/') + '/rest/v1/kinds', params={
                        'select': 'kind_code,name,species,kind_aliases(alias)', 'active': 'eq.true',
                        'species': f'eq.{species}', 'order': 'kind_code', 'offset': offset, 'limit': 1000})
                    response.raise_for_status()
                    page = response.json()
                    for row in page:
                        aliases = row.pop('kind_aliases', [])
                        rows.extend([{**row, 'alias': a['alias']} for a in aliases] or [{**row, 'alias': None}])
                    if len(page) < 1000:
                        break
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

    async def lookup(self, species: str, name: str = '') -> list[dict]:
        """축종 및 선택 품종명으로 활성 DB 품종 조회 (LIKE %품종명%)."""
        # Literal substring matching is LIKE with user wildcards escaped.
        query = normalize(name)
        rows = await self.rows(species)
        unique = {r['kind_code']: {k: ('etc' if r[k] == 'other' else r[k]) for k in ('kind_code', 'name', 'species')}
                  for r in rows if query in normalize(r['name'])}
        return list(unique.values())
