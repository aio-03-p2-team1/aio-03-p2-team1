"""실종 위치 기준 검색 반경 (실종 후 지난 날짜에 따라 단계적으로 넓힌다).

- 반경은 직선거리(km)다. 도로 거리·이동 시간이 아니다.
- 실종 위치: 사용자가 지도에서 고른 동 단위 주소(criteria.lost_place)를 서버가 카카오로 좌표 변환한다.
  클라이언트가 보낸 좌표는 쓰지 않는다.
- 공고 위치: 공고의 관할 시군구(care.org, 예: '서울특별시 강서구') 중심 좌표로 근사한다.
  좌표를 구하지 못한 공고는 '거리 미확인'으로 남기고 제외하지 않는다(누락 ≠ 불일치).
- 반경 밖으로 확인된 공고만 제외한다. 제외된 공고는 임베딩하지 않는다.
- 범위 확대는 사용자 동의가 필요하다. 이 모듈은 단계만 계산하고, 넓히기는 그래프의 ask 경로가 맡는다.
"""

from __future__ import annotations

import asyncio
import math
from datetime import date
from typing import Any

from backend.tools.kakao import KakaoError

RADIUS_VERSION = "radius-v1"
# 단계별 반경(km). 마지막 단계(None)는 반경 없이 조회 지역(시·도) 전체.
RADIUS_STEPS_KM: tuple[float | None, ...] = (3.0, 10.0, 20.0, None)
# 실종 후 지난 날짜 → 추천 단계 (이하 기준)
STEP_BY_DAYS = ((3, 0), (7, 1), (14, 2))
MAX_GEOCODE_REQUESTS = 40  # 한 번의 검색에서 카카오에 새로 묻는 주소 수 상한(캐시 적중은 제외)

# 프로세스 메모리 좌표 캐시: 성공한 좌표만 넣는다(실패·오류는 캐시하지 않음).
_COORD_CACHE: dict[str, tuple[float, float]] = {}


def recommended_step(lost_date: str | None, today: date | None = None) -> int:
    """실종 날짜가 없으면 반경 없이(마지막 단계) 찾는다."""
    if not lost_date:
        return len(RADIUS_STEPS_KM) - 1
    try:
        days = ((today or date.today()) - date.fromisoformat(lost_date)).days
    except ValueError:
        return len(RADIUS_STEPS_KM) - 1
    for limit, step in STEP_BY_DAYS:
        if days <= limit:
            return step
    return len(RADIUS_STEPS_KM) - 1


def effective_step(criteria: dict[str, Any], today: date | None = None) -> int:
    """사용자가 넓히기에 동의한 단계(radius_step)가 있으면 그 값, 없으면 추천 단계."""
    chosen = criteria.get("radius_step")
    if isinstance(chosen, int) and 0 <= chosen < len(RADIUS_STEPS_KM):
        return chosen
    return recommended_step(criteria.get("lost_date") or criteria.get("start_date"), today)


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


async def _coord(kakao, address: str, counter: dict[str, int]) -> tuple[float, float] | None:
    key = " ".join(address.split())
    if key in _COORD_CACHE:
        counter["cached"] += 1
        return _COORD_CACHE[key]
    if counter["requests"] >= MAX_GEOCODE_REQUESTS:
        counter["skipped"] += 1
        return None
    counter["requests"] += 1
    try:
        result = await kakao.geocode(key)
    except KakaoError:
        counter["errors"] += 1
        return None
    if result.get("status") != "ok":
        counter["not_found"] += 1
        return None
    point = (float(result["lat"]), float(result["lng"]))
    _COORD_CACHE[key] = point
    return point


async def apply_radius(kakao, criteria: dict[str, Any], items: list[dict[str, Any]], today: date | None = None) -> dict[str, Any]:
    """반환: {"items": 반경 안 + 거리 미확인 공고, "radius": 화면·이력용 요약, "call": 도구 호출 요약 또는 None}."""
    step = effective_step(criteria, today)
    radius_km = RADIUS_STEPS_KM[step]
    base = {
        "version": RADIUS_VERSION,
        "step": step,
        "max_step": len(RADIUS_STEPS_KM) - 1,
        "radius_km": radius_km,
        "next_radius_km": RADIUS_STEPS_KM[step + 1] if step + 1 < len(RADIUS_STEPS_KM) else None,
        "lost_place": criteria.get("lost_place"),
        "basis": "jurisdiction_center",
        "distance": "straight_line",
    }
    if radius_km is None:
        return {"items": items, "radius": {**base, "applied": False, "reason": "whole_region"}, "call": None}
    if not items:
        return {"items": items, "radius": {**base, "applied": False, "reason": "no_items"}, "call": None}
    if not criteria.get("lost_place"):
        return {"items": items, "radius": {**base, "applied": False, "reason": "lost_place_missing"}, "call": None}
    if not getattr(kakao, "configured", False):
        return {"items": items, "radius": {**base, "applied": False, "reason": "not_configured"}, "call": None}

    counter = {"requests": 0, "cached": 0, "errors": 0, "not_found": 0, "skipped": 0}
    center = await _coord(kakao, criteria["lost_place"], counter)
    if center is None:
        call = {"requests": counter["requests"], "cached": counter["cached"], "outcome": "center_unavailable"}
        return {"items": items, "radius": {**base, "applied": False, "reason": "center_unavailable"}, "call": call}

    orgs = sorted({(item.get("care") or {}).get("org") for item in items if (item.get("care") or {}).get("org")})
    points = await asyncio.gather(*(_coord(kakao, org, counter) for org in orgs))
    org_point = dict(zip(orgs, points))

    kept: list[dict[str, Any]] = []
    inside = unknown = outside = 0
    for item in items:
        point = org_point.get((item.get("care") or {}).get("org"))
        if point is None:
            unknown += 1
            kept.append({**item, "distance_km": None, "distance_basis": "unknown"})
            continue
        km = round(haversine_km(center, point), 1)
        if km <= radius_km:
            inside += 1
            kept.append({**item, "distance_km": km, "distance_basis": "jurisdiction_center"})
        else:
            outside += 1
    summary = {
        **base,
        "applied": True,
        "center": {"lat": center[0], "lng": center[1]},
        "inside": inside,
        "unknown": unknown,
        "excluded": outside,
    }
    call = {**counter, "orgs": len(orgs), "outcome": "ok"}
    return {"items": kept, "radius": summary, "call": call}
