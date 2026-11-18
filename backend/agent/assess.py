"""에이전트 요청(사진·추가 정보)의 서버 규칙: 보기 목록, 반복 제한, 문장 검증.

검색 에이전트(search_agent.py)가 request_photo / request_info 를 고르면 여기서 검증해 화면 요청으로 만든다.
- 버튼 보기(options)는 서버 목록에서만 나온다(LLM이 새 값을 만들지 못하게).
- 사용자에게 보이는 이유 문장에 숫자·링크가 있거나 너무 길면 서버 고정 문구로 바꾼다(번호·날짜 지어내기 방지).
- 같은 대화에서 사진 1회·정보 2회까지, 이미 받은 정보·이미 물은 항목·'모르겠어요' 항목은 다시 묻지 않는다.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from backend.schemas.common import Color

log = logging.getLogger("dasimanna.assess")

MAX_PHOTO_REQUESTS = 1  # 한 대화에서 사진 요청 최대 횟수
MAX_INFO_REQUESTS = 2  # 한 대화에서 추가 정보 요청 최대 횟수
REASON_MAX = 60

# 버튼 보기는 서버가 정한다(LLM이 새 값을 만들지 못하게). 털색은 검색이 이해하는 색 목록과 같다.
FIELD_OPTIONS: dict[str, list[str]] = {
    "color": ["흰색", "갈색", "검정", "크림", "회색", "황갈색", "노랑", "삼색", "고등어무늬"],
    "size": ["소형", "중형", "대형"],
    "sex": ["수컷", "암컷"],
    "marks": ["목줄·옷 착용", "얼룩·점", "꼬리 짧음", "귀 처짐", "귀 섬", "털 짧음", "털 김"],
}
FIELD_LABELS = {"color": "털색", "size": "크기", "sex": "성별", "marks": "눈에 띄는 특징"}
# 입력 신호 키: 이미 준 정보는 다시 묻지 않는다.
FIELD_GIVEN = {"color": "color_given", "size": "size_given", "sex": "sex_given", "marks": "marks_given"}
DEFAULT_REASON = {
    "photo": "사진이 있으면 닮은 동물을 더 정확히 골라 드릴 수 있어요.",
    "color": "털색을 알려 주시면 후보를 더 좁힐 수 있어요.",
    "size": "크기를 알려 주시면 후보를 더 좁힐 수 있어요.",
    "sex": "성별을 알려 주시면 후보를 더 좁힐 수 있어요.",
    "marks": "눈에 띄는 특징이 있으면 비슷한 후보를 더 잘 찾을 수 있어요.",
}
assert set(FIELD_OPTIONS["color"]) <= set(Color.__args__)  # 털색 보기는 검색 색 목록 안에서만

REASON_LABELS = {
    "few_features": "입력한 특징이 적음",
    "mixed_breed": "믹스견이라 글만으로 구분이 어려움",
    "weak_similarity": "가장 비슷한 후보도 유사도가 낮음",
    "flat_top": "상위 후보끼리 차이가 거의 없음",
    "no_feature_match": "1등 후보도 입력 특징과 맞는 근거가 없음",
}


def allowed_actions(confidence: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
    """반복 요청 제한과 이미 받은 정보를 반영해 고를 수 있는 행동을 계산한다(서버 규칙)."""
    signals = confidence.get("signals") or {}
    asked = history.get("asked_fields") or []
    declined = history.get("declined") or []
    fields = []
    if history.get("info_requests", 0) < MAX_INFO_REQUESTS:
        fields = [f for f in FIELD_OPTIONS
                  if not signals.get(FIELD_GIVEN[f]) and f not in asked and f not in declined]
    photo = (history.get("photo_requests", 0) < MAX_PHOTO_REQUESTS and not signals.get("photo_given")
             and "photo" not in declined)
    return {"photo": photo, "fields": fields}


def _clean_reason(text: Any, key: str) -> str:
    """보이는 문장을 검증한다. 숫자가 있거나(번호·날짜 지어내기 방지) 비었거나 길면 고정 문구로 바꾼다."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text or len(text) > REASON_MAX or re.search(r"[0-9０-９]", text) or re.search(r"https?:|@", text):
        return DEFAULT_REASON[key]
    return text


def build_request(name: str, args: dict[str, Any], allowed: dict[str, Any]) -> dict[str, Any] | None:
    """LLM이 고른 도구를 서버 규칙으로 검증해 화면용 요청으로 만든다. 허용되지 않으면 None(요청 없음)."""
    if name == "request_photo" and allowed["photo"]:
        return {"type": "photo", "reason": _clean_reason(args.get("reason"), "photo")}
    if name == "request_info":
        field = args.get("field")
        if field in allowed["fields"]:
            return {"type": "info", "field": field, "label": FIELD_LABELS[field],
                    "options": list(FIELD_OPTIONS[field]), "reason": _clean_reason(args.get("reason"), field)}
    return None
