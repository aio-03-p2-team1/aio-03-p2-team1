"""Fetch API kinds and synchronize them into the configured Supabase schema.

Apply scripts/bootstrap_schema.sql in Supabase SQL Editor before running this loader.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

import httpx

try:
    from .kind_sync import ALIASES, fetch_records, normalize
except ImportError:  # direct execution: python scripts/init_kinds_supabase.py
    from kind_sync import ALIASES, fetch_records, normalize


class SupabaseSink:
    def __init__(self, settings):
        service_key = settings.supabase_service_role_key.get_secret_value()
        self.client = httpx.Client(
            base_url=settings.supabase_url.rstrip("/") + "/rest/v1",
            timeout=30,
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Accept-Profile": settings.supabase_schema,
                "Content-Profile": settings.supabase_schema,
            },
        )

    def sync(self, records: list[dict]) -> None:
        self.client.patch(
            "/kinds?active=eq.true",
            json={"active": False, "updated_at": datetime.now(timezone.utc).isoformat()},
        ).raise_for_status()
        for offset in range(0, len(records), 500):
            self.client.post(
                "/kinds?on_conflict=kind_code",
                json=records[offset:offset + 500],
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            ).raise_for_status()
        self.client.delete("/kind_aliases?source=eq.curated").raise_for_status()
        now = datetime.now(timezone.utc).isoformat()
        aliases = [
            {
                "kind_code": record["kind_code"],
                "alias": alias,
                "search_alias": normalize(alias),
                "source": "curated",
                "created_at": now,
                "updated_at": now,
            }
            for record in records
            for alias in ALIASES.get(normalize(record["name"]), [])
        ]
        if aliases:
            self.client.post(
                "/kind_aliases", json=aliases, headers={"Prefer": "return=minimal"}
            ).raise_for_status()

    def close(self) -> None:
        self.client.close()


async def main() -> int:
    from backend.config import Settings

    settings = Settings()
    if settings.storage_backend != "supabase":
        raise RuntimeError("Supabase 초기화에는 STORAGE_BACKEND=supabase 를 설정하세요")
    records = await fetch_records(settings)
    sink = SupabaseSink(settings)
    try:
        sink.sync(records)
    finally:
        sink.close()
    print(f"품종 동기화 완료: {len(records)}건, backend=supabase")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"품종 Supabase 동기화 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
