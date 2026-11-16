"""Shared public API access and normalization for the backend-specific loaders."""
from __future__ import annotations

import asyncio
import re
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


def require_api_key(settings: Settings) -> str:
    if settings.animal_api_key is None:
        raise RuntimeError("ANIMAL_API_KEY 가 설정되지 않았습니다")
    return settings.animal_api_key.get_secret_value()


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def parse_items(payload: dict) -> tuple[int, list[dict]]:
    """Parse the public API response.body.items.item envelope."""
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
    """Fetch every page; retry failed or truncated results up to three times."""
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
            # HTTP exceptions can include the serviceKey in their URL; never print them.
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
    return {
        "species": species,
        "kind_code": code,
        "name": name,
        "search_name": normalize(name),
        "active": True,
        "source": "animal_api",
        "source_updated_at": now,
        "created_at": now,
        "updated_at": now,
    }


async def fetch_records(settings: Settings) -> list[dict]:
    require_api_key(settings)
    now = datetime.now(timezone.utc).isoformat()
    records = []
    async with httpx.AsyncClient(timeout=30) as client:
        for up_code, species in SPECIES.items():
            items = await fetch_all(client, settings, up_code)
            records.extend(normalize_record(species, item, now) for item in items)
    if not records:
        raise RuntimeError("품종 API 응답이 비어 있어 DB를 변경하지 않았습니다")
    return records
