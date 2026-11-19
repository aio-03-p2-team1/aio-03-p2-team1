"""보호자 글의 중성화·나이·몸무게와 구조동물 공고 값(neuterYn·age·weight)을 같은 단위로 맞춘다.

- 보호자 값은 입력 검토 LLM이 글에서 옮겨 적은 표현을 받아, 숫자가 원래 글에 실제로 있을 때만 쓴다(값을 지어내지 않게).
- 공고 값은 보호소 추정이라 자주 틀리므로 거르지 않고 비슷한지만 본다.
"""

from __future__ import annotations

import re

_NUMBER = r"(\d+(?:\.\d+)?)"
_AGE = re.compile(_NUMBER + r"\s*(개월|달|살|세|년생|년)")
_WEIGHT = re.compile(_NUMBER + r"\s*(kg|㎏|킬로|키로|g|그램)", re.IGNORECASE)
_NOTICE_YEAR = re.compile(r"((?:19|20)\d{2})")
_NOTICE_WEIGHT = re.compile(_NUMBER)

AGE_TOLERANCE_YEARS = 2  # 보호소 나이는 추정값이라 ±2살까지 비슷하다고 본다
ADULT_YEARS = 2  # 이 나이 이상이면 새끼 공고(나이 0)와는 같은 개체일 수 없다고 본다
WEIGHT_TOLERANCE = 0.3  # 몸무게는 ±30%(작은 동물은 최소 1kg)까지 비슷하다고 본다


def _in_source(number: str, source: str) -> bool:
    """뽑은 숫자가 보호자가 쓴 글에 그대로 있는지(다른 숫자의 일부가 아닌지) 확인한다."""
    return re.search(r"(?<![\d.])" + re.escape(number) + r"(?![\d])", source) is not None


def user_neuter(value: str, source: str) -> str:
    """'Y'·'N'·''. 글에 '중성화'라는 말이 있을 때만 쓴다."""
    return value if value in ("Y", "N") and "중성화" in (source or "") else ""


def user_age_years(value: str, source: str) -> float | None:
    """'3살'·'6개월' 같은 표현을 나이(년)로. 숫자가 글에 없거나 '2020년생'처럼 연도면 None."""
    match = _AGE.search(value or "")
    if not match or not _in_source(match.group(1), source or ""):
        return None
    number, unit = float(match.group(1)), match.group(2)
    if unit in ("년생",) or number >= 100:
        return None  # 출생 연도는 기준 해가 애매해 쓰지 않는다
    years = number / 12 if unit in ("개월", "달") else number
    return round(years, 2) if 0 <= years <= 40 else None


def user_weight_kg(value: str, source: str) -> float | None:
    match = _WEIGHT.search(value or "")
    if not match or not _in_source(match.group(1), source or ""):
        return None
    number = float(match.group(1))
    kg = number / 1000 if match.group(2).lower() in ("g", "그램") else number
    return round(kg, 2) if 0 < kg <= 150 else None


def age_label(years: float) -> str:
    return f"약 {round(years * 12)}개월" if years < 1 else f"약 {years:g}살"


def notice_age_years(age: str | None, year: int) -> float | None:
    """공고 나이 '2023(년생)'을 기준 해의 나이로. '60일미만(년생)'처럼 어린 개체는 0."""
    text = age or ""
    if "일미만" in text or ("개월" in text and not _NOTICE_YEAR.search(text)):
        return 0.0
    match = _NOTICE_YEAR.search(text)
    if not match:
        return None
    born = int(match.group(1))
    return float(year - born) if born <= year else None


def notice_weight_kg(weight: str | None) -> float | None:
    match = _NOTICE_WEIGHT.search(weight or "")
    if not match:
        return None
    kg = float(match.group(1))
    return kg if 0 < kg <= 150 else None


def age_close(wanted: float, notice: float) -> bool:
    return abs(wanted - notice) <= AGE_TOLERANCE_YEARS


def weight_close(wanted: float, notice: float) -> bool:
    return abs(wanted - notice) <= max(1.0, wanted * WEIGHT_TOLERANCE)
