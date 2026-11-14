"""분실동물 조회 API 연결 확인 스크립트.

    uv run python scripts/inspect_lost_api.py            # 최근 14일
    uv run python scripts/inspect_lost_api.py --days 30

.env 의 LOST_ANIMAL_API_KEY 로 lossInfo 를 실제 호출하고 아래만 출력한다.
- 결과 건수(totalCount), 받은 항목 수
- 응답 항목의 필드 이름 목록과 각 필드가 값이 채워진 항목 수

필드 *값*은 출력하지 않는다. 신고자 이름·연락처 같은 개인정보가 들어 있을 수 있어서다.
화면에 어떤 필드를 보여 주고 어떤 필드를 버릴지 정하는 데 쓴다.

    uv run python scripts/inspect_lost_api.py --samples

--samples 를 주면 개인정보가 아닌 필드(SAFE_FIELDS)만 예시 값 3개씩 더 출력한다.
신고자 이름·연락처·마이크로칩 번호·상세 주소는 이 옵션에서도 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import Settings  # noqa: E402
from backend.tools.lost_animal_api import MAX_ROWS, LostAnimalApi, LostAnimalApiError  # noqa: E402

# 예시 값을 출력해도 되는 필드. callName·callTel(신고자), rfidCd(마이크로칩), happenAddrDtl(상세 주소)은 제외.
SAFE_FIELDS = ("age", "colorCd", "happenAddr", "happenDt", "happenPlace", "kindCd", "orgNm", "popfile", "sexCd", "specialMark")


async def fetch_all(api: LostAnimalApi, start: date, end: date, rows: int) -> tuple[int, list[dict], int]:
    """첫 페이지의 totalCount에 맞춰 모든 페이지를 순서대로 조회한다."""
    rows = max(1, min(rows, MAX_ROWS))
    first = await api.search(start=start, end=end, page=1, rows=rows)
    items = list(first.items)
    page_count = max(1, (first.total_count + rows - 1) // rows)
    pages_fetched = 1
    for page_no in range(2, page_count + 1):
        page = await api.search(start=start, end=end, page=page_no, rows=rows)
        pages_fetched += 1
        items.extend(page.items)
        if not page.items:
            break
    return first.total_count, items, pages_fetched


async def main(days: int, rows: int, samples: bool) -> int:
    settings = Settings()
    if settings.lost_animal_api_key is None:
        print("LOST_ANIMAL_API_KEY 가 .env 에 없습니다.")
        return 1
    api = LostAnimalApi(settings.lost_animal_api_base_url, settings.lost_animal_api_key.get_secret_value())
    end = date.today()
    start = end - timedelta(days=days)
    try:
        total_count, items, pages_fetched = await fetch_all(api, start, end, rows)
    except LostAnimalApiError as exc:
        # 키 값은 출력하지 않는다. 오류 종류와 포털 결과 코드만 보여 준다.
        print(f"호출 실패: {exc.code} (HTTP {exc.status}, resultCode {exc.result_code})")
        return 1
    finally:
        await api.aclose()

    filled = Counter(k for item in items for k, v in item.items() if v not in (None, "", " "))
    fields = sorted({k for item in items for k in item})
    print(f"조회 기간: {start} ~ {end}")
    print(f"전체 건수(totalCount): {total_count} / 받은 항목: {len(items)} / 조회 페이지: {pages_fetched}")
    print("필드 (값이 채워진 항목 수):")
    for name in fields:
        print(f"  {name}: {filled.get(name, 0)}")
    if samples:
        print("예시 값 (개인정보가 아닌 필드만, 최대 3개):")
        for name in SAFE_FIELDS:
            values = [str(item[name])[:60] for item in items if item.get(name)][:3]
            print(f"  {name}: {values}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="분실동물 조회 API 연결 확인(필드 이름만 출력)")
    parser.add_argument("--days", type=int, default=14, help="오늘부터 며칠 전까지 조회할지 (기본 14)")
    parser.add_argument("--rows", type=int, default=MAX_ROWS, help="페이지당 항목 수 (기본·최대 1000)")
    parser.add_argument("--samples", action="store_true", help="개인정보가 아닌 필드의 예시 값도 출력")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.days, args.rows, args.samples)))
