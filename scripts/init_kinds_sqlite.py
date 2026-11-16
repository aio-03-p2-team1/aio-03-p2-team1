"""Fetch API kinds and synchronize them into the configured SQLite database."""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from .kind_sync import ALIASES, fetch_records, normalize
except ImportError:  # direct execution: python scripts/init_kinds_sqlite.py
    from kind_sync import ALIASES, fetch_records, normalize

BOOTSTRAP_SQL = Path(__file__).resolve().with_name("bootstrap_sqlite.sql")


class SqliteSink:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(BOOTSTRAP_SQL.read_text(encoding="utf-8"))

    def sync(self, records: list[dict]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute("UPDATE kinds SET active=0, updated_at=?", (now,))
        self.db.executemany(
            """INSERT INTO kinds(species,kind_code,name,search_name,active,source,source_updated_at,created_at,updated_at)
            VALUES(:species,:kind_code,:name,:search_name,:active,:source,:source_updated_at,:created_at,:updated_at)
            ON CONFLICT(kind_code) DO UPDATE SET species=excluded.species,name=excluded.name,
            search_name=excluded.search_name,active=1,source=excluded.source,
            source_updated_at=excluded.source_updated_at,updated_at=excluded.updated_at""",
            records,
        )
        # Keep old kind rows, but refresh the curated alias set from the current API snapshot.
        self.db.execute("DELETE FROM kind_aliases WHERE source='curated'")
        for record in records:
            for alias in ALIASES.get(normalize(record["name"]), []):
                self.db.execute(
                    """INSERT OR REPLACE INTO kind_aliases
                    (kind_code,alias,search_alias,source,created_at,updated_at)
                    VALUES(?,?,?,'curated',?,?)""",
                    (record["kind_code"], alias, normalize(alias), now, now),
                )
        self.db.commit()

    def close(self) -> None:
        self.db.close()


async def main() -> int:
    from backend.config import Settings

    settings = Settings()
    if settings.storage_backend != "sqlite":
        raise RuntimeError("SQLite 초기화에는 STORAGE_BACKEND=sqlite 를 설정하세요")
    records = await fetch_records(settings)
    sink = SqliteSink(settings.sqlite_path)
    try:
        sink.sync(records)
    finally:
        sink.close()
    print(f"품종 동기화 완료: {len(records)}건, backend=sqlite")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"품종 SQLite 동기화 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
