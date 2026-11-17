"""Audio object storage for public missing-pet board posts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import quote

import httpx

from backend.storage import StorageError


class PostAudioStore:
    def __init__(self, *, backend: str, local_dir: str, url: str = "", bucket: str = "", service_key: str = "", timeout: float = 30):
        self.backend = backend
        self.root = Path(local_dir)
        self.bucket = bucket
        self.client = None
        if backend == "supabase":
            self.client = httpx.AsyncClient(
                base_url=url.rstrip("/") + "/storage/v1",
                timeout=timeout,
                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            )

    def _local_path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise StorageError("audio_storage_error")
        return path

    def _remote_path(self, key: str) -> str:
        return "/object/" + quote(self.bucket, safe="") + "/" + "/".join(quote(part, safe="") for part in key.split("/"))

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        if self.backend == "supabase":
            try:
                response = await self.client.post(self._remote_path(key), content=data, headers={"Content-Type": content_type, "x-upsert": "false"})
            except httpx.HTTPError as exc:
                raise StorageError("audio_storage_unavailable") from exc
            if response.status_code >= 400:
                raise StorageError("audio_storage_unavailable", response.status_code)
            return

        path = self._local_path(key)
        try:
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, data)
        except OSError as exc:
            raise StorageError("audio_storage_unavailable") from exc

    async def get(self, key: str) -> bytes | None:
        if self.backend == "supabase":
            try:
                response = await self.client.get(self._remote_path(key))
            except httpx.HTTPError as exc:
                raise StorageError("audio_storage_unavailable") from exc
            if response.status_code == 404:
                return None
            if response.status_code >= 400:
                raise StorageError("audio_storage_unavailable", response.status_code)
            return response.content
        path = self._local_path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StorageError("audio_storage_unavailable") from exc

    async def delete(self, key: str) -> None:
        if self.backend == "supabase":
            try:
                response = await self.client.delete(self._remote_path(key))
            except httpx.HTTPError as exc:
                raise StorageError("audio_storage_unavailable") from exc
            if response.status_code >= 400 and response.status_code != 404:
                raise StorageError("audio_storage_unavailable", response.status_code)
            return
        path = self._local_path(key)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError as exc:
            raise StorageError("audio_storage_unavailable") from exc

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
