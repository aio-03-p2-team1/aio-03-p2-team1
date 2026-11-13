"""Supabase(PostgREST) 저장소.

- 지정 스키마 "aio-03-p2-team1-demo" 의 documents 테이블을 쓴다(public 금지).
- 스키마는 Accept-Profile / Content-Profile 헤더로 지정한다.
  Data API 의 Exposed schemas 에 없으면 406 / PGRST106 이 난다.
- service_role 키를 apikey 와 Bearer 헤더에 함께 넣는다(11장).
- 오류 메시지에 응답 본문·키를 넣지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from backend.storage import StorageError, check_kind


class SupabaseStore:
    def __init__(self, url: str, schema: str, service_key: str, timeout: float = 30, transport=None):
        self._schema = schema
        self._client = httpx.AsyncClient(
            base_url=url.rstrip("/") + "/rest/v1",
            timeout=timeout,
            transport=transport,
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Accept-Profile": schema,
                "Content-Profile": schema,
            },
        )

    async def _request(self, method: str, params: dict, json_body=None, prefer: str | None = None):
        headers = {"Prefer": prefer} if prefer else {}
        try:
            res = await self._client.request(method, "/documents", params=params, json=json_body, headers=headers)
        except httpx.TimeoutException as exc:
            raise StorageError("storage_timeout") from exc
        except httpx.HTTPError as exc:
            raise StorageError("storage_network") from exc
        if res.status_code == 409:
            return res
        if res.status_code >= 400:
            code = "storage_error"
            try:
                if res.json().get("code") == "PGRST106":
                    code = "storage_invalid_schema"
            except ValueError:
                pass
            if res.status_code in (401, 403):
                code = "storage_auth"
            raise StorageError(code, res.status_code)
        return res

    @staticmethod
    def _key(owner, kind, doc_id=None):
        params = {"owner": f"eq.{owner}", "kind": f"eq.{kind}"}
        if doc_id is not None:
            params["id"] = f"eq.{doc_id}"
        return params

    async def get(self, owner, kind, doc_id):
        check_kind(kind)
        res = await self._request("GET", {**self._key(owner, kind, doc_id), "select": "data"})
        rows = res.json()
        return rows[0]["data"] if rows else None

    async def put(self, owner, kind, doc_id, data: dict[str, Any]):
        check_kind(kind)
        body = {
            "owner": owner,
            "kind": kind,
            "id": doc_id,
            "data": data,

            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._request(
            "POST",
            {"on_conflict": "owner,kind,id"},
            json_body=body,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    async def create(self, owner, kind, doc_id, data):
        check_kind(kind)
        res = await self._request(
            "POST",
            {},
            json_body={"owner": owner, "kind": kind, "id": doc_id, "data": data},
            prefer="return=minimal",
        )
        return res.status_code != 409

    async def list(self, owner, kind, limit=50):
        check_kind(kind)
        res = await self._request(
            "GET",
            {**self._key(owner, kind), "select": "id,data,updated_at", "order": "updated_at.desc", "limit": str(limit)},
        )
        return res.json()

    async def delete(self, owner, kind, doc_id):
        check_kind(kind)
        res = await self._request("DELETE", self._key(owner, kind, doc_id), prefer="return=representation")
        return bool(res.json())
