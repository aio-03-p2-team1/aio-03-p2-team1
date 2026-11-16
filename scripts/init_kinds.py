"""품종 기준 데이터를 공공데이터 API에서 동기화한다.

실행: uv run python scripts/init_kinds.py
STORAGE_BACKEND=sqlite 는 SQLITE_PATH DB, supabase 는 SUPABASE_SCHEMA Data API를 사용한다.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import Settings  # noqa: E402

SPECIES = {"417000": "dog", "422400": "cat", "429900": "other"}
ALIASES = {
    "래브라도리트리버": ["래브라도 리트리버", "라브라도 리트리버"],
    "저먼셰퍼드": ["저먼 셰퍼드", "독일 셰퍼드"],
    "코리안숏헤어": ["코리안 숏헤어", "한국 고양이", "코숏"],
    "믹스견": ["믹스", "혼종견"],
}

BOOTSTRAP_SQL = Path(__file__).resolve().with_name("bootstrap_schema.sql")


def require_api_key(settings: Settings) -> str:
    if settings.animal_api_key is None:
        raise RuntimeError("ANIMAL_API_KEY 가 설정되지 않았습니다")
    return settings.animal_api_key.get_secret_value()

def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()

def parse_items(payload: dict) -> tuple[int, list[dict]]:
    """공공데이터포털 공통 response.body.items.item 형식을 읽는다."""
    response = payload.get("response", payload)
    header = response.get("header", {})
    if str(header.get("resultCode", "00")) not in {"00", "0", "None"}:
        raise RuntimeError(f"API 오류 resultCode={header.get('resultCode')}")
    body = response.get("body", {}) or {}
    raw = (body.get("items") or {}).get("item", [])
    if isinstance(raw, dict):
        raw = [raw]
    return int(body.get("totalCount", len(raw)) or 0), raw

async def fetch_all(
    client: httpx.AsyncClient,
    settings: Settings,
    up_kind_cd: str,
    *,
    sleep=asyncio.sleep,
) -> list[dict]:
    """Fetch pages and retry failed or short responses (3 retries after first attempt)."""
    api_key = require_api_key(settings)
    last_error: Exception | None = None
    for attempt in range(4):
        collected: list[dict] = []
        expected_count: int | None = None
        page = 1
        try:
            while expected_count is None or len(collected) < expected_count:
                response = await client.get(f"{settings.animal_api_base_url}/kind_v2", params={
                    "serviceKey": api_key,
                    "up_kind_cd": up_kind_cd,
                    "_type": "json",
                    "numOfRows": 1000,
                    "pageNo": page,
                })
                response.raise_for_status()
                total, items = parse_items(response.json())
                expected_count = max(expected_count or 0, total)
                collected.extend(items)
                if not items:
                    break
                page += 1
            if expected_count is not None and len(collected) >= expected_count:
                return collected
            last_error = RuntimeError(
                f"totalCount 응답 부족 (축종 코드 {up_kind_cd}: {len(collected)}/{expected_count})"
            )
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            # HTTP 예외의 str 에는 serviceKey가 포함된 URL이 들어갈 수 있어 출력하지 않는다.
            last_error = exc
        if attempt < 3:
            await sleep(0.5 * (2 ** attempt))
    detail = str(last_error) if isinstance(last_error, RuntimeError) else type(last_error).__name__
    raise RuntimeError(f"품종 API 조회 실패 (축종 코드 {up_kind_cd}): {detail}") from None

def normalize_record(species: str, item: dict, now: str) -> dict:
    code = str(item.get("kind_cd") or item.get("kindCd") or item.get("kind_code") or "").strip()
    name = str(item.get("KNm") or item.get("kind_nm") or item.get("kindNm") or item.get("kind_name") or item.get("name") or "").strip()
    if not code or not name:
        raise RuntimeError("품종 API 항목에 품종 코드/이름이 없습니다")
    return {"species": species, "kind_code": code, "name": name, "search_name": normalize(name),
            "active": True, "source": "animal_api", "source_updated_at": now, "created_at": now, "updated_at": now}

class SqliteSink:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(BOOTSTRAP_SQL.read_text(encoding="utf-8"))
    def sync(self, records: list[dict]):
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute("UPDATE kinds SET active=0, updated_at=?", (now,))
        self.db.executemany("""INSERT INTO kinds(species,kind_code,name,search_name,active,source,source_updated_at,created_at,updated_at)
          VALUES(:species,:kind_code,:name,:search_name,:active,:source,:source_updated_at,:created_at,:updated_at)
          ON CONFLICT(kind_code) DO UPDATE SET species=excluded.species,name=excluded.name,search_name=excluded.search_name,
          active=1,source=excluded.source,source_updated_at=excluded.source_updated_at,updated_at=excluded.updated_at""", records)
        # 이번 응답에 없는 코드는 삭제하지 않고 비활성 처리해 코드 변경 이력을 보존한다.
        self.db.execute("DELETE FROM kind_aliases WHERE source='curated'")
        for record in records:
            for alias in ALIASES.get(normalize(record['name']), []):
                self.db.execute("INSERT OR REPLACE INTO kind_aliases(kind_code,alias,search_alias,source,created_at,updated_at) VALUES(?,?,?,'curated',?,?)",
                                (record['kind_code'], alias, normalize(alias), now, now))
        self.db.commit()
    def close(self): self.db.close()

class SupabaseSink:
    def __init__(self, settings: Settings):
        self.client = httpx.Client(base_url=settings.supabase_url.rstrip('/') + '/rest/v1', timeout=30,
            headers={"apikey": settings.supabase_service_role_key.get_secret_value(),
                     "Authorization": f"Bearer {settings.supabase_service_role_key.get_secret_value()}",
                     "Accept-Profile": settings.supabase_schema, "Content-Profile": settings.supabase_schema})
    def sync(self, records: list[dict]):
        # SQL migration creates the schema and indexes; upsert current source data and retain missing codes inactive.
        self.client.patch('/kinds?active=eq.true', json={"active": False, "updated_at": datetime.now(timezone.utc).isoformat()}).raise_for_status()
        for i in range(0, len(records), 500):
            self.client.post('/kinds?on_conflict=kind_code', json=records[i:i+500],
                headers={"Prefer":"resolution=merge-duplicates,return=minimal"}).raise_for_status()
        self.client.delete('/kind_aliases?source=eq.curated').raise_for_status()
        aliases=[]
        now=datetime.now(timezone.utc).isoformat()
        for record in records:
            aliases.extend({"kind_code":record['kind_code'],"alias":a,"search_alias":normalize(a),"source":"curated","created_at":now,"updated_at":now}
                           for a in ALIASES.get(normalize(record['name']), []))
        if aliases:
            self.client.post('/kind_aliases',json=aliases,headers={"Prefer":"return=minimal"}).raise_for_status()
    def close(self):
        self.client.close()

async def main() -> int:
    settings=Settings()
    require_api_key(settings)
    records=[]
    now=datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(timeout=30) as client:
        for up_code,species in SPECIES.items():
            records.extend(normalize_record(species,item,now) for item in await fetch_all(client,settings,up_code))
    if not records:
        raise RuntimeError("품종 API 응답이 비어 있어 DB를 변경하지 않았습니다")
    sink=SqliteSink(settings.sqlite_path) if settings.storage_backend == "sqlite" else SupabaseSink(settings)
    try:
        sink.sync(records)
    finally:
        sink.close()
    print(f"품종 동기화 완료: {len(records)}건, backend={settings.storage_backend}")
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"품종 동기화 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
