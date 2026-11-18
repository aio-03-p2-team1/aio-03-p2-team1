"""서비스 기준 날짜(한국 시간).

서버(Render)는 UTC 로 돌 수 있다. 사용자는 한국에 있으므로 '오늘'은 항상 한국 날짜로 계산한다.
UTC 기준으로 계산하면 한국 시간 0시~9시에는 서버가 아직 '어제'라서
오늘 날짜로 검색하면 미래 날짜 오류가 나고, 실종 후 경과일·반경 단계가 하루 어긋난다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def kst_today() -> date:
    """한국 날짜 기준 오늘."""
    return datetime.now(KST).date()
