"""Fetch up to 50,000 unique protection-animal records into a temporary SQLite DB.

Usage: uv run python scripts/fetch_animal_color_groups.py
Data is stored in /tmp/dasimanna-animal-colors.sqlite3, not the app database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import Settings

API_PATH = "abandonmentPublic_v2"
ROWS_PER_PAGE = 1000  # data.go.kr documents a maximum of 1,000 rows per page.
MAX_RECORDS = 50_000
CONCURRENCY = 5


def response_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get("response")
    if not isinstance(response, dict):
        raise RuntimeError("API 응답에 response 객체가 없습니다")
    header = response.get("header") or {}
    if str(header.get("resultCode", "")) not in {"00", "0", "000"}:
        raise RuntimeError(f"구조동물 API 오류 코드: {header.get('resultCode', 'unknown')}")
    body = response.get("body") or {}
    items = body.get("items") or {}
    item = items.get("item") if isinstance(items, dict) else None
    if item is None:
        return []
    return item if isinstance(item, list) else [item]


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS animals (
            desertion_no TEXT PRIMARY KEY,
            color_cd TEXT,
            raw_json TEXT NOT NULL
        )
    """)
    return db


async def fetch_page(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    key: str,
    page: int,
    start: date,
    end: date,
) -> tuple[int, list[dict[str, Any]], int]:
    params = {
        "serviceKey": key,
        "_type": "json",
        "pageNo": page,
        "numOfRows": ROWS_PER_PAGE,
        "bgnde": start.strftime("%Y%m%d"),
        "endde": end.strftime("%Y%m%d"),
    }
    async with semaphore:
        response = await client.get(f"/{API_PATH}", params=params)
    response.raise_for_status()
    payload = response.json()
    rows = response_items(payload)
    body = payload["response"].get("body") or {}
    try:
        total = int(body.get("totalCount") or 0)
    except (TypeError, ValueError):
        raise RuntimeError("API 응답의 totalCount가 숫자가 아닙니다")
    return page, rows, total


def store_page(db: sqlite3.Connection, rows: list[dict[str, Any]]) -> int:
    inserted = 0
    for row in rows:
        # data.go.kr field contract: desertionNo is the animal identifier; colorCd is coat color.
        animal_id = row.get("desertionNo")
        if animal_id is None or str(animal_id).strip() == "":
            continue
        cursor = db.execute(
            "INSERT OR IGNORE INTO animals(desertion_no, color_cd, raw_json) VALUES (?, ?, ?)",
            (str(animal_id), row.get("colorCd"), json.dumps(row, ensure_ascii=False)),
        )
        inserted += cursor.rowcount
    db.commit()
    return inserted


async def collect(db_path: Path, limit: int = MAX_RECORDS, first_year: int = 2000) -> int:
    settings = Settings()
    if settings.animal_api_key is None:
        raise RuntimeError("ANIMAL_API_KEY 설정이 필요합니다")
    key = unquote(settings.animal_api_key.get_secret_value())
    semaphore = asyncio.Semaphore(CONCURRENCY)
    timeout = httpx.Timeout(30.0, connect=10.0)
    db = open_db(db_path)
    async with httpx.AsyncClient(base_url=settings.animal_api_base_url.rstrip("/"), timeout=timeout) as client:
        try:
            current = db.execute("SELECT COUNT(*) FROM animals").fetchone()[0]
            print(f"existing unique animals={current}; target={limit}", flush=True)
            today = date.today()
            for year in range(today.year, first_year - 1, -1):
                last_month = today.month if year == today.year else 12
                for month in range(last_month, 0, -1):
                    if current >= limit:
                        break
                    start = date(year, month, 1)
                    end = date(year, month, monthrange(year, month)[1])
                    if end > today:
                        end = today
                    _, first_rows, total = await fetch_page(client, semaphore, key, 1, start, end)
                    page_count = (total + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE
                    added = store_page(db, first_rows[:max(0, limit - current)])
                    current += added
                    print(f"{start:%Y-%m}: page 1/{page_count}, total={total}, new={added}, unique={current}", flush=True)
                    if current >= limit:
                        break
                    tasks = [fetch_page(client, semaphore, key, page_no, start, end)
                             for page_no in range(2, page_count + 1)]
                    for task in asyncio.as_completed(tasks):
                        fetched_page, page_rows, _ = await task
                        added = store_page(db, page_rows[:max(0, limit - current)])
                        current += added
                        print(f"{start:%Y-%m}: page {fetched_page}/{page_count}, new={added}, unique={current}", flush=True)
                        if current >= limit:
                            break
                if current >= limit:
                    break
        finally:
            db.close()
    print(f"unique animals in DB={current}; target={limit}; db={db_path}")
    return current


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=MAX_RECORDS, choices=range(1, MAX_RECORDS + 1))
    parser.add_argument("--db", type=Path, default=Path("/tmp/dasimanna-animal-colors.sqlite3"))
    parser.add_argument("--first-year", type=int, default=2000)
    args = parser.parse_args()
    asyncio.run(collect(args.db, args.limit, args.first_year))


if __name__ == "__main__":
    main()
