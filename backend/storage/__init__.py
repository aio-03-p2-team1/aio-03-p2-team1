"""문서 저장소.

SQLite(로컬)와 Supabase(운영)를 같은 인터페이스로 제공한다.
모든 문서는 (owner, kind, id) 로 식별하고, owner 는 로그인 사용자 키다.
실종 정보 게시판(kind=post)만 공용 소유자 키 "board" 아래에 저장한다(routers/posts.py).
댓글(kind=comment)은 게시글마다 소유자 키 "comment:<게시글 ID>" 아래에 저장한다(routers/comments.py).
"""

from __future__ import annotations

from typing import Any, Protocol

KINDS = {"identity", "thread", "memory", "saved", "run", "subscription", "notification", "post", "comment", "poster", "asset"}


class StorageError(RuntimeError):

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


class Store(Protocol):
    async def get(self, owner: str, kind: str, doc_id: str) -> dict[str, Any] | None: ...

    async def put(self, owner: str, kind: str, doc_id: str, data: dict[str, Any]) -> None: ...

    async def create(self, owner: str, kind: str, doc_id: str, data: dict[str, Any]) -> bool:

        ...

    async def list(self, owner: str, kind: str, limit: int = 50) -> list[dict[str, Any]]:

        ...

    async def delete(self, owner: str, kind: str, doc_id: str) -> bool: ...

    async def list_kind(self, kind: str, limit: int = 100, offset: int = 0,
                        fields: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        """관리자 화면용: 소유자와 관계없이 한 종류의 문서를 최근 순으로 읽는다.

        반환 행 = {owner, id, updated_at, data}. fields 를 주면 data 에 그 최상위 키만 담는다(큰 후보 목록 제외).
        """
        ...

    async def aclose(self) -> None: ...


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


FIELD_NAME = __import__("re").compile(r"^[a-z][a-z0-9_]{0,40}$")


def check_fields(fields) -> tuple[str, ...] | None:
    if fields is None:
        return None
    fields = tuple(fields)
    if not fields or not all(FIELD_NAME.match(f) for f in fields):
        raise ValueError("잘못된 필드 이름")
    return fields
