"""요청 조건 정규화·검증 (prompt.md 4장 입력 검증, 8장 기억 적용 순서)."""

from __future__ import annotations

from datetime import date
from typing import Any

SPECIES_ALIASES = {
    "dog": "dog", "개": "dog", "강아지": "dog",
    "cat": "cat", "고양이": "cat",
    "etc": "etc", "기타": "etc",
    "all": "all", "전체": "all",
}
REGION_ALL = {"all", "전체", "전국", "전체 지역"}
OPTIONAL_FIELDS = ("pet_name", "breed", "color", "sex", "age", "size", "description", "lost_place", "lost_date")

QUESTION_TEXT = {
    "species": "찾는 동물의 종류를 알려 주세요. (개 · 고양이 · 기타 · 전체)",
    "region": "어느 지역의 보호소 공고를 찾아볼까요? 모르면 '전체'를 선택해 주세요.",
    "period": "언제부터 언제까지의 공고를 찾아볼까요? 실종 날짜를 알려 주시면 그날부터 오늘까지 찾습니다.",
}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def merge_conditions(current: dict[str, Any], session: dict[str, Any] | None, memory: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, str]]:
    """현재 요청 → 같은 세션의 확인된 조건 → 확인된 장기 기억 순서로 채운다.

    반환: (병합 결과, 각 필드의 출처)
    장기 기억은 동물 특징(선택 항목)만 채우고 지역·기간·종류 같은 검색 범위는 채우지 않는다.
    """
    merged: dict[str, Any] = {}
    origin: dict[str, str] = {}
    keys = {"species", "region", "start_date", "end_date", "radius_step", *OPTIONAL_FIELDS}
    for key in keys:
        for source_name, source in (("request", current), ("session", session or {})):
            value = _clean(source.get(key))
            if value:
                merged[key] = value
                origin[key] = source_name
                break
    for key in OPTIONAL_FIELDS:
        if key not in merged and memory and _clean(memory.get(key)):
            merged[key] = _clean(memory[key])
            origin[key] = "memory"
    return merged, origin


def normalize(raw: dict[str, Any], today: date | None = None) -> tuple[dict[str, Any], list[str], list[dict[str, str]]]:
    """반환: (정규화 조건, 누락 필수 항목, 입력 오류)."""
    today = today or date.today()
    criteria: dict[str, Any] = {}
    missing: list[str] = []
    errors: list[dict[str, str]] = []

    species_raw = _clean(raw.get("species")).lower()
    if not species_raw:
        missing.append("species")
    elif species_raw not in SPECIES_ALIASES:
        errors.append({"field": "species", "code": "unsupported_species", "message": "지원하지 않는 동물 종류입니다."})
    else:
        criteria["species"] = SPECIES_ALIASES[species_raw]

    region_raw = _clean(raw.get("region"))
    if not region_raw:
        missing.append("region")
    else:
        criteria["region"] = "all" if region_raw in REGION_ALL else region_raw

    start_raw = _clean(raw.get("start_date")) or _clean(raw.get("lost_date"))
    end_raw = _clean(raw.get("end_date")) or (today.isoformat() if start_raw else "")
    if not start_raw:
        missing.append("period")
    else:
        try:
            start = date.fromisoformat(start_raw)
            end = date.fromisoformat(end_raw)
        except ValueError:
            errors.append({"field": "period", "code": "invalid_date", "message": "날짜 형식(YYYY-MM-DD)을 확인해 주세요."})
        else:
            if start > today or end > today:
                errors.append({"field": "period", "code": "future_date", "message": "미래 날짜는 검색할 수 없습니다."})
            elif start > end:
                errors.append({"field": "period", "code": "date_reversed", "message": "시작일이 종료일보다 늦습니다."})
            else:
                criteria["start_date"] = start.isoformat()
                criteria["end_date"] = end.isoformat()

    for key in OPTIONAL_FIELDS:
        value = _clean(raw.get(key))
        if value:
            criteria[key] = value[:500]
    # 반경 단계: 사용자가 넓히기에 동의했을 때만 들어온다(0~3). 장기 기억에서는 채우지 않는다.
    step_raw = _clean(raw.get("radius_step"))
    if step_raw.isdigit() and 0 <= int(step_raw) <= 3:
        criteria["radius_step"] = int(step_raw)
    if criteria.get("sex") and criteria["sex"] not in ("M", "F"):
        criteria["sex"] = {"수컷": "M", "남아": "M", "암컷": "F", "여아": "F"}.get(criteria["sex"], "")
        if not criteria["sex"]:
            criteria.pop("sex")
    return criteria, missing, errors


def questions_for(missing: list[str], errors: list[dict[str, str]]) -> list[dict[str, str]]:
    out = [{"field": m, "message": QUESTION_TEXT[m]} for m in missing]
    out += [{"field": e["field"], "message": e["message"]} for e in errors]
    return out
