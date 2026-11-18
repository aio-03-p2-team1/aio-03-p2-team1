"""분실 신고 목록 캐시 (실종 정보 게시판용).

속도를 위해 지키는 것
1. 한 번에 몰아서 가져온다: 기간(start~end) 하나에 대해 개·고양이·기타 3번만 동시에 호출한다
   (numOfRows=1000). 종류·지역 필터와 페이지 나누기는 받은 목록에서 서버 메모리로 처리한다.
   → 필터를 바꾸거나 다음 페이지를 눌러도 API 를 다시 부르지 않는다.
2. 기간별로 10분 캐시한다(FRESH_SECONDS). 하루 호출 한도(개발계정 10,000회)도 아낀다.
3. 10분이 지났어도 1시간 안의 목록이면 바로 돌려주고, 새 목록은 뒤에서 받아 바꿔 둔다(STALE_SECONDS).
   → 사용자는 거의 항상 캐시 응답을 받는다.
4. 같은 기간을 동시에 여러 요청이 원하면 API 호출은 한 번만 하고 결과를 나눠 쓴다.

정확성
- 호출이 실패하면 빈 목록이 아니라 LostAnimalApiError 를 낸다. 빈 결과(0건)와 실패를 구분한다.
- 개인정보는 normalize_lost() 에서 이미 빠진 상태로만 캐시에 들어간다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.tools.lost_animal_api import MAX_ROWS, LostAnimalApiError, normalize_lost

log = logging.getLogger("dasimanna")

SPECIES = ("dog", "cat", "etc")
FRESH_SECONDS = 600  # 이 시간 안의 목록은 그대로 쓴다
STALE_SECONDS = 3600  # 이 시간 안의 목록은 먼저 돌려주고 뒤에서 새로 받는다
MAX_PAGES = 3  # 축종별 최대 페이지(1,000건 × 3). 넘는 건수는 truncated 로 알린다
MAX_PERIODS = 8  # 캐시에 둘 기간 수
MAX_DETAIL = 5000  # 상세 조회용으로 기억할 신고 수


@dataclass
class LostSnapshot:
    """한 기간의 분실 신고 목록."""

    items: list[dict[str, Any]]  # 분실 날짜 최신순, 개인정보 제거된 게시판 글 형태
    total_count: int  # API 가 알려 준 전체 건수(3개 축종 합)
    truncated: bool  # MAX_PAGES 때문에 다 받지 못했으면 True
    fetched_at: float  # time.monotonic()


class LostFeed:
    def __init__(self, api, clock=time.monotonic):
        self.api = api  # LostAnimalApi(또는 시험용 가짜)
        self._clock = clock
        # 최근에 쓴 기간을 뒤로 보내는 LRU. 상세 조회용 하루짜리 기간이 기본 목록을 밀어내지 않게 한다.
        self._cache: "OrderedDict[tuple[date, date], LostSnapshot]" = OrderedDict()
        self._inflight: dict[tuple[date, date], asyncio.Task] = {}
        self._by_id: dict[str, dict[str, Any]] = {}

    async def aclose(self) -> None:
        for task in self._inflight.values():
            task.cancel()
        close = getattr(self.api, "aclose", None)
        if close:
            await close()

    # ── 목록 ──────────────────────────────────────────────

    async def snapshot(self, start: date, end: date) -> LostSnapshot:
        """기간의 분실 신고 목록. 캐시 → (오래됐으면 뒤에서 새로 받기) → 없으면 지금 받기."""
        key = (start, end)
        cached = self._cache.get(key)
        if cached:
            self._cache.move_to_end(key)
        age = self._clock() - cached.fetched_at if cached else None
        if cached and age < FRESH_SECONDS:
            return cached
        if cached and age < STALE_SECONDS:
            self._start_fetch(key)  # 기다리지 않는다. 실패해도 이전 목록을 계속 쓴다.
            return cached
        return await self._start_fetch(key)

    def _start_fetch(self, key: tuple[date, date]) -> asyncio.Task:
        task = self._inflight.get(key)
        if task is None or task.done():
            task = asyncio.ensure_future(self._fetch(*key))
            task.add_done_callback(lambda t, k=key: self._finish(k, t))
            self._inflight[key] = task
        return task

    def _finish(self, key, task: asyncio.Task) -> None:
        self._inflight.pop(key, None)
        if not task.cancelled() and task.exception() is not None:
            # 실패를 기록한다. 기다리던 요청에는 예외가 그대로 전달되고, 뒤에서 받던 경우엔 이전 목록을 계속 쓴다.
            log.warning("lost feed fetch failed code=%s", getattr(task.exception(), "code", type(task.exception()).__name__))

    async def _fetch(self, start: date, end: date) -> LostSnapshot:
        # 축종 3개를 동시에 호출한다. 하나라도 실패하면 전체를 실패로 본다(일부만 보여 주면 빈 결과로 오해할 수 있음).
        results = await asyncio.gather(*(self._fetch_species(start, end, sp) for sp in SPECIES))
        items: list[dict[str, Any]] = []
        total = 0
        truncated = False
        seen: set[str] = set()
        for species_items, species_total, species_truncated in results:
            total += species_total
            truncated = truncated or species_truncated
            for item in species_items:
                if item["id"] in seen:  # 같은 신고가 두 번 오면 하나만 남긴다
                    continue
                seen.add(item["id"])
                items.append(item)
        items.sort(key=lambda i: i["lost_date"] or "", reverse=True)
        snap = LostSnapshot(items=items, total_count=total, truncated=truncated, fetched_at=self._clock())
        self._cache[(start, end)] = snap
        self._cache.move_to_end((start, end))
        while len(self._cache) > MAX_PERIODS:
            self._cache.popitem(last=False)
        self._remember(items)
        return snap

    async def _fetch_species(self, start: date, end: date, species: str) -> tuple[list[dict], int, bool]:
        first = await self.api.search(start=start, end=end, species=species, page=1, rows=MAX_ROWS)
        pages = [first]
        # 1,000건이 넘을 때만 다음 페이지를 동시에 받는다(보통은 1번 호출로 끝).
        last_page = min(MAX_PAGES, -(-first.total_count // MAX_ROWS))
        if last_page > 1:
            pages += await asyncio.gather(*(
                self.api.search(start=start, end=end, species=species, page=n, rows=MAX_ROWS)
                for n in range(2, last_page + 1)
            ))
        items = [normalize_lost(raw, species) for page in pages for raw in page.items]
        truncated = first.total_count > MAX_PAGES * MAX_ROWS
        return [i for i in items if i], first.total_count, truncated

    # ── 상세 ──────────────────────────────────────────────

    def _remember(self, items: list[dict[str, Any]]) -> None:
        for item in items:
            self._by_id[item["id"]] = item
        while len(self._by_id) > MAX_DETAIL:
            self._by_id.pop(next(iter(self._by_id)))

    async def get(self, item_id: str) -> dict[str, Any] | None:
        """ID 로 신고 하나를 찾는다. 기억에 없으면 ID 의 날짜 하루만 다시 조회한다(3회 호출)."""
        item = self._by_id.get(item_id)
        if item:
            return item
        try:
            day = date(int(item_id[5:9]), int(item_id[9:11]), int(item_id[11:13]))
        except (ValueError, IndexError):
            return None
        await self.snapshot(day, day)
        return self._by_id.get(item_id)


__all__ = ["LostFeed", "LostSnapshot", "LostAnimalApiError"]
