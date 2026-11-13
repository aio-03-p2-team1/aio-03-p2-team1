"""로컬 개발용 SQLite 저장소. 운영(Render)에서는 임시 파일시스템이므로 쓰지 않는다."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.storage import check_kind

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    owner TEXT NOT NULL,
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (owner, kind, id)
);
CREATE INDEX IF NOT EXISTS documents_owner_kind_updated
    ON documents (owner, kind, updated_at DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteStore:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    async def _run(self, fn, *args):
        def call():
            with self._lock:
                return fn(*args)

        return await asyncio.to_thread(call)

    async def get(self, owner, kind, doc_id):
        check_kind(kind)

        def q():
            row = self._conn.execute(
                "SELECT data FROM documents WHERE owner=? AND kind=? AND id=?", (owner, kind, doc_id)
            ).fetchone()
            return json.loads(row[0]) if row else None

        return await self._run(q)

    async def put(self, owner, kind, doc_id, data: dict[str, Any]):
        check_kind(kind)

        def q():
            self._conn.execute(
                "INSERT INTO documents(owner,kind,id,data,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(owner,kind,id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                (owner, kind, doc_id, json.dumps(data, ensure_ascii=False), _now()),
            )
            self._conn.commit()

        await self._run(q)

    async def create(self, owner, kind, doc_id, data):
        check_kind(kind)

        def q():
            try:
                self._conn.execute(
                    "INSERT INTO documents(owner,kind,id,data,updated_at) VALUES(?,?,?,?,?)",
                    (owner, kind, doc_id, json.dumps(data, ensure_ascii=False), _now()),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

        return await self._run(q)

    async def list(self, owner, kind, limit=50):
        check_kind(kind)

        def q():
            rows = self._conn.execute(
                "SELECT id, data, updated_at FROM documents WHERE owner=? AND kind=? "
                "ORDER BY updated_at DESC LIMIT ?",
                (owner, kind, limit),
            ).fetchall()
            return [{"id": r[0], "data": json.loads(r[1]), "updated_at": r[2]} for r in rows]

        return await self._run(q)

    async def delete(self, owner, kind, doc_id):
        check_kind(kind)

        def q():
            cur = self._conn.execute(
                "DELETE FROM documents WHERE owner=? AND kind=? AND id=?", (owner, kind, doc_id)
            )
            self._conn.commit()
            return cur.rowcount > 0

        return await self._run(q)
