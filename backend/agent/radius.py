"""실종 위치 기준 검색 반경 (실종 후 지난 날짜에 따라 단계적으로 넓힌다).

- 반경은 직선거리(km)다. 도로 거리·이동 시간이 아니다.
- 실종 위치(반경 중심): 사용자가 지도에서 찍은 좌표(criteria.lost_lat/lost_lng)를 쓴다.
  좌표는 criteria.normalize 에서 숫자·한국 범위를 검사한 값만 들어온다. 좌표가 없으면(이전 화면, API 직접 호출)
  실종 위치 주소(criteria.lost_place)를 서버가 카카오로 좌표 변환한다.
  좌표를 조작해도 그 사용자 자신의 검색 결과만 바뀌므로 다른 사용자·데이터에 영향이 없다.
- 공고 위치: 공고의 구조 장소(happen_place)에서 읍·면·동 이름을 뽑아 '관할 시군구 + 읍면동'
  (예: '경상북도 경주시 외동읍') 중심 좌표로 근사한다(distance_basis=rescue_area).
  읍·면·동을 못 뽑거나 좌표를 못 구하면 관할 시군구(care.org) 중심으로 대신한다(jurisdiction_center).
  경주시처럼 넓은 시·군은 시청 좌표와 실제 구조 장소가 20km 가까이 떨어질 수 있어서다.
  둘 다 못 구한 공고는 '거리 미확인'으로 남기고 제외하지 않는다(누락 ≠ 불일치).
- 반경 밖으로 확인된 공고만 제외한다. 제외된 공고는 임베딩하지 않는다.
- 범위 확대는 사용자 동의가 필요하다. 이 모듈은 단계만 계산하고, 넓히기는 그래프의 ask 경로가 맡는다.
"""

from __future__ import annotations

import asyncio
import math
import re
from datetime import date
from typing import Any

from backend.timeutil import kst_today
from backend.tools.kakao import KakaoError

RADIUS_VERSION = "radius-v1"
# 단계별 반경(km). 마지막 단계(None)는 반경 없이 조회 지역(시·도) 전체.
RADIUS_STEPS_KM: tuple[float | None, ...] = (3.0, 10.0, 20.0, None)
# 실종 후 지난 날짜 → 추천 단계 (이하 기준)
STEP_BY_DAYS = ((3, 0), (7, 1), (14, 2))
MAX_GEOCODE_REQUESTS = 80  # 한 번의 검색에서 카카오에 새로 묻는 주소 수 상한(캐시 적중은 제외). 시군구 먼저, 남는 몫으로 읍면동

# 구조 장소 글에서 읍·면·동 이름만 뽑는다. 한글로 시작하고 앞부분이 두 글자 이상인 낱말이 읍/면/동으로 끝나야 한다.
# - '306동'(아파트 동 번호), '홍은동주민센터옆'(붙여 쓴 말)은 뽑지 않는다.
# - '이동'·'운동'처럼 일반 낱말과 겹치는 두 글자 이름도 뽑지 않는다(엉뚱한 지역으로 잡힐 수 있어서).
# 못 뽑으면 관할 시군구 중심으로 대신한다.
_AREA_TOKEN = re.compile(r"(?<![가-힣0-9])([가-힣][가-힣0-9]{1,8}(?:읍|면|동))(?![가-힣0-9])")

# 프로세스 메모리 좌표 캐시: 성공한 좌표만 넣는다(실패·오류는 캐시하지 않음).
_COORD_CACHE: dict[str, tuple[float, float]] = {}


def area_token(happen_place: str | None) -> str | None:
    """구조 장소에서 첫 읍·면·동 이름. 예: '외동읍 석계평리길 부근' → '외동읍'. 없으면 None."""
    match = _AREA_TOKEN.search(happen_place or "")
    return match.group(1) if match else None


def rescue_area(item: dict[str, Any]) -> str | None:
    """'관할 시군구 + 읍면동' 주소. 관할이나 읍면동을 모르면 None."""
    org = (item.get("care") or {}).get("org")
    token = area_token(item.get("happen_place"))
    if not org or not token or token in org:
        return None
    return f"{org} {token}"


def recommended_step(lost_date: str | None, today: date | None = None) -> int:
    """실종 날짜가 없으면 반경 없이(마지막 단계) 찾는다."""
    if not lost_date:
        return len(RADIUS_STEPS_KM) - 1
    try:
        days = ((today or kst_today()) - date.fromisoformat(lost_date)).days  # 한국 날짜 기준 경과일
    except ValueError:
        return len(RADIUS_STEPS_KM) - 1
    for limit, step in STEP_BY_DAYS:
        if days <= limit:
            return step
    return len(RADIUS_STEPS_KM) - 1


def days_since(lost_date: str | None, today: date | None = None) -> int | None:
    """실종 후 지난 날(한국 날짜 기준). 날짜가 없거나 읽을 수 없으면 None."""
    if not lost_date:
        return None
    try:
        return ((today or kst_today()) - date.fromisoformat(lost_date)).days
    except ValueError:
        return None


def next_widen_day(step: int) -> int | None:
    """자동 단계에서 다음 단계로 넓어지는 경과일(예: 3km 단계 → 4일째부터 10km). 마지막 단계면 None."""
    for limit, s in STEP_BY_DAYS:
        if s == step:
            return limit + 1
    return None


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
        # 동 이름은 법정동·행정동이 함께 나와 여러 건이 된다. 반경 중심·관할 근사에는 첫 문서를 쓴다.
        result = await kakao.geocode(key, allow_ambiguous=True)
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
    auto = not isinstance(criteria.get("radius_step"), int)  # False: 사용자가 넓히기를 골랐음
    base = {
        # 화면 안내("실종 후 N일 → M km")용. 화면에서 따로 계산하지 않고 이 값을 그대로 보여 준다.
        "days_since_lost": days_since(criteria.get("lost_date") or criteria.get("start_date"), today),
        "auto": auto,
        "next_widen_day": next_widen_day(step) if auto else None,
        "version": RADIUS_VERSION,
        "step": step,
        "max_step": len(RADIUS_STEPS_KM) - 1,
        "radius_km": radius_km,
        "next_radius_km": RADIUS_STEPS_KM[step + 1] if step + 1 < len(RADIUS_STEPS_KM) else None,
        "lost_place": criteria.get("lost_place"),
        "basis": "rescue_area_or_jurisdiction",  # 구조 장소 읍면동 우선, 없으면 관할 시군구 중심
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
    if isinstance(criteria.get("lost_lat"), float) and isinstance(criteria.get("lost_lng"), float):
        center, center_source = (criteria["lost_lat"], criteria["lost_lng"]), "user_pin"  # 지도에서 찍은 점
    else:
        center, center_source = await _coord(kakao, criteria["lost_place"], counter), "address"
    if center is None:
        call = {"requests": counter["requests"], "cached": counter["cached"], "outcome": "center_unavailable"}
        return {"items": items, "radius": {**base, "applied": False, "reason": "center_unavailable"}, "call": call}

    # 1) 관할 시군구 중심(대체용) 2) 구조 장소 읍면동 중심(우선). 같은 주소는 한 번만 조회한다.
    orgs = sorted({(item.get("care") or {}).get("org") for item in items if (item.get("care") or {}).get("org")})
    org_points = await asyncio.gather(*(_coord(kakao, org, counter) for org in orgs))
    org_point = dict(zip(orgs, org_points))
    areas = sorted({a for a in (rescue_area(item) for item in items) if a})
    area_points = await asyncio.gather(*(_coord(kakao, area, counter) for area in areas))
    area_point = dict(zip(areas, area_points))

    kept: list[dict[str, Any]] = []
    inside = unknown = outside = by_area = 0
    for item in items:
        area = rescue_area(item)
        point, basis = (area_point.get(area), "rescue_area") if area else (None, None)
        if point is None:
            point, basis = org_point.get((item.get("care") or {}).get("org")), "jurisdiction_center"
        if point is None:
            unknown += 1
            kept.append({**item, "distance_km": None, "distance_basis": "unknown"})
            continue
        by_area += basis == "rescue_area"
        km = round(haversine_km(center, point), 1)
        if km <= radius_km:
            inside += 1
            kept.append({**item, "distance_km": km, "distance_basis": basis})
        else:
            outside += 1
    summary = {
        **base,
        "applied": True,
        "center": {"lat": center[0], "lng": center[1]},
        "center_source": center_source,  # user_pin: 사용자가 찍은 좌표, address: 주소를 좌표로 변환
        "inside": inside,
        "unknown": unknown,
        "excluded": outside,
        "by_rescue_area": by_area,  # 구조 장소 읍면동으로 거리를 잰 공고 수(나머지는 관할 시군구 중심)
    }
    call = {**counter, "orgs": len(orgs), "areas": len(areas), "outcome": "ok"}
    return {"items": kept, "radius": summary, "call": call}
