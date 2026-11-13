"""문서 저장소 (prompt.md 11장).

SQLite(로컬)와 Supabase(운영)를 같은 인터페이스로 제공한다.
모든 문서는 (owner, kind, id) 로 식별하고, owner 는 로그인 사용자 키다.
"""

from __future__ import annotations

from typing import Any, Protocol

KINDS = {"identity", "thread", "memory", "saved", "run", "subscription", "notification"}


class StorageError(RuntimeError):
    """저장소 호출 실패. code 는 화면에 보여도 되는 분류 코드다."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


class Store(Protocol):
    async def get(self, owner: str, kind: str, doc_id: str) -> dict[str, Any] | None: ...

    async def put(self, owner: str, kind: str, doc_id: str, data: dict[str, Any]) -> None: ...

    async def create(self, owner: str, kind: str, doc_id: str, data: dict[str, Any]) -> bool:
        """이미 있으면 False (create-only)."""
        ...

    async def list(self, owner: str, kind: str, limit: int = 50) -> list[dict[str, Any]]:
        """updated_at 내림차순. 각 항목은 {"id", "data", "updated_at"}."""
        ...

    async def delete(self, owner: str, kind: str, doc_id: str) -> bool: ...


def check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"지원하지 않는 문서 종류: {kind}")


def build_store(settings) -> Store:
    if settings.storage_backend == "supabase":
        from backend.storage.supabase import SupabaseStore

        return SupabaseStore(
            url=settings.supabase_url,
            schema=settings.supabase_schema,
            service_key=settings.supabase_service_role_key.get_secret_value(),
            timeout=settings.request_timeout_seconds,
        )
    from backend.storage.sqlite import SqliteStore

    return SqliteStore(settings.sqlite_path)
