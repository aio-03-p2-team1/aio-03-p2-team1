"""검색 날짜 기준이 한국 시간인지 시험한다.

서버가 UTC 로 돌면 한국 시간 0시~9시에는 서버 날짜가 하루 늦다.
그때 '오늘' 실종 날짜로 검색해도 미래 날짜 오류가 나지 않아야 하고, 반경 단계도 한국 날짜로 계산해야 한다.
"""

from datetime import date, datetime, timedelta, timezone

from backend import timeutil
from backend.agent import criteria as crit
from backend.agent import radius


def test_kst_today_is_utc_plus_nine():
    now = datetime.now(timezone.utc)
    assert timeutil.kst_today() in {(now + timedelta(hours=9)).date(), (now + timedelta(hours=9, seconds=5)).date()}


def test_today_lost_date_is_not_future_in_early_kst_morning(monkeypatch):
    # 한국 11/16 08:00 = UTC 11/15 23:00. 서버 date.today() 는 11/15 이지만 한국 기준 오늘은 11/16 이다.
    monkeypatch.setattr(crit, "kst_today", lambda: date(2026, 11, 16))
    criteria, missing, errors = crit.normalize({"species": "dog", "region": "전체", "lost_date": "2026-11-16"})
    assert errors == [] and missing == []
    assert criteria["start_date"] == "2026-11-16" and criteria["end_date"] == "2026-11-16"


def test_radius_step_uses_kst_today(monkeypatch):
    monkeypatch.setattr(radius, "kst_today", lambda: date(2026, 11, 16))
    assert radius.recommended_step("2026-11-13") == 0  # 3일 경과 → 3km
    assert radius.recommended_step("2026-11-12") == 1  # 4일 경과 → 10km


def test_new_lost_date_replaces_previous_session_period():
    # 같은 대화에서 실종 날짜를 바꿔 다시 검색하면, 이전 검색의 시작일이 아니라 새 실종 날짜부터 찾아야 한다.
    session = {"species": "dog", "region": "서울특별시", "lost_date": "2026-11-14",
               "start_date": "2026-11-14", "end_date": "2026-11-16"}
    merged, origin = crit.merge_conditions({"lost_date": "2026-11-13"}, session, None)
    assert "start_date" not in merged and merged["lost_date"] == "2026-11-13"
    criteria, _, errors = crit.normalize(merged, today=date(2026, 11, 16))
    assert errors == [] and criteria["start_date"] == "2026-11-13"
    # 실종 날짜 없이 다른 값만 보내면(예: 반경 넓히기) 이전 기간을 그대로 쓴다.
    merged, _ = crit.merge_conditions({"radius_step": "1"}, session, None)
    assert merged["start_date"] == "2026-11-14"
