"""assess 노드: 검색 결과가 애매할 때 LLM이 도구(함수 호출)로 다음 행동을 고른다.

흐름: validate 가 확신 신호(confidence)를 계산 → 낮으면 이 모듈이 LLM에 도구 3개를 주고 하나를 고르게 한다.
- request_photo  : 사진을 올려 달라고 요청(사진 분석 → 특징 추출 → 같은 대화로 다시 검색)
- request_info   : 털색·크기·특징·성별 중 하나를 버튼으로 물어봄
- accept_results : 지금 결과로 충분하다고 판단(요청 없음)

사실을 지어내지 않도록 두 겹으로 막는다.
1) 프롬프트: 공고 번호·날짜·숫자·연락처를 말하지 말고, 보기는 서버가 정한다고 알려 준다.
2) 서버 검증: LLM은 '무엇을 물을지(field)'와 짧은 이유만 고른다. 버튼 보기(options)는 서버 목록에서만 나오고,
   이유 글에 숫자가 있거나 너무 길면 서버의 고정 문구로 바꾼다. 이미 물었거나 사용자가 '모르겠어요'한 항목은 다시 묻지 않는다.
LLM이 없거나 실패하면 accept_results 와 같게 처리한다(검색 결과는 그대로 보여 준다).
결과는 막지 않는다: 요청 카드가 나와도 후보 목록은 함께 보여 준다.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.schemas.common import Color

log = logging.getLogger("dasimanna.assess")

ASSESS_PROMPT_VERSION = "assess-v1"
MAX_PHOTO_REQUESTS = 1  # 한 대화에서 사진 요청 최대 횟수
MAX_INFO_REQUESTS = 2  # 한 대화에서 추가 정보 요청 최대 횟수
REASON_MAX = 60

# 버튼 보기는 서버가 정한다(LLM이 새 값을 만들지 못하게). 털색은 검색이 이해하는 색 목록과 같다.
FIELD_OPTIONS: dict[str, list[str]] = {
    "color": ["흰색", "갈색", "검정", "크림", "회색", "황갈색", "노랑", "삼색", "고등어"],
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

SYSTEM_PROMPT = """너는 잃어버린 반려동물 검색 서비스의 판단 담당이다.
검색은 이미 끝났고 결과도 사용자에게 보여 준다. 너는 결과가 애매할 때 사용자에게 무엇을 더 요청할지 도구 하나로 고른다.

규칙:
- 반드시 도구 하나만 호출한다: request_photo, request_info, accept_results.
- 제공된 '허용 행동' 안에서만 고른다. 허용되지 않은 도구나 field는 고르지 않는다.
- 믹스견처럼 품종·털색 글만으로 구분이 어려우면 사진(request_photo)이 가장 도움이 된다.
- 입력 특징이 적으면 아직 받지 않은 정보 중 가장 구분에 도움이 되는 하나(request_info)를 고른다.
- 결과가 충분히 그럴듯하면 accept_results 를 고른다.
- reason/note 는 사용자에게 보이는 한국어 한 문장(60자 이내), 존댓말로 쓴다.
- 공고 번호, 날짜, 숫자, 연락처, 보호소 이름, 동물의 특징을 지어내지 않는다. 받은 신호에 없는 사실을 말하지 않는다.
- 버튼 보기는 서버가 정하므로 보기를 만들지 않는다."""

REASON_LABELS = {
    "few_features": "입력한 특징이 적음",
    "mixed_breed": "믹스견이라 글만으로 구분이 어려움",
    "weak_similarity": "가장 비슷한 후보도 유사도가 낮음",
    "flat_top": "상위 후보끼리 차이가 거의 없음",
    "no_feature_match": "1등 후보도 입력 특징과 맞는 근거가 없음",
}


class RequestPhoto(BaseModel):
    """사용자에게 잃어버린 동물 사진을 올려 달라고 요청한다. 사진에서 특징을 뽑아 다시 검색한다."""

    reason: str = Field(description="사용자에게 보일 요청 이유 한 문장(숫자·날짜·번호 금지)")


class RequestInfo(BaseModel):
    """사용자에게 정보 하나를 버튼으로 물어본다. 보기는 서버가 정한다."""

    field: Literal["color", "size", "sex", "marks"] = Field(description="물어볼 항목")
    reason: str = Field(description="사용자에게 보일 요청 이유 한 문장(숫자·날짜·번호 금지)")


class AcceptResults(BaseModel):
    """지금 결과로 충분하다고 판단한다. 사용자에게 추가 요청을 하지 않는다."""

    note: str = Field(description="판단 이유 한 문장(기록용)")


TOOLS = [RequestPhoto, RequestInfo, AcceptResults]
TOOL_NAMES = {"RequestPhoto": "request_photo", "RequestInfo": "request_info", "AcceptResults": "accept_results",
              "request_photo": "request_photo", "request_info": "request_info", "accept_results": "accept_results"}


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


def describe(confidence: dict[str, Any], allowed: dict[str, Any]) -> str:
    """LLM에 줄 입력. 계산된 신호만 넣는다(공고 내용·개인정보는 넣지 않는다)."""
    s = confidence.get("signals") or {}
    lines = [
        "애매한 이유: " + ", ".join(REASON_LABELS.get(r, r) for r in confidence.get("reasons") or []),
        f"받은 정보: 품종={'있음' if s.get('breed_given') else '없음'}{'(믹스)' if s.get('breed_mixed') else ''}, "
        f"털색={'있음' if s.get('color_given') else '없음'}, 크기={'있음' if s.get('size_given') else '없음'}, "
        f"성별={'있음' if s.get('sex_given') else '없음'}, 특징={'있음' if s.get('marks_given') else '없음'}, "
        f"사진={'있음' if s.get('photo_given') else '없음'}",
        f"후보 수: {s.get('candidates')}, 1등 유사도: {s.get('top_similarity')}, 1·2등 차이: {s.get('similarity_gap')}",
        "허용 행동: "
        + ", ".join(
            (["request_photo"] if allowed["photo"] else [])
            + ([f"request_info(field: {'|'.join(allowed['fields'])})"] if allowed["fields"] else [])
            + ["accept_results"]
        ),
    ]
    return "\n".join(lines)


class Assessor:
    """LangChain 채팅 모델에 도구를 묶어(bind_tools) 하나를 고르게 한다. 시험에서는 가짜 client를 주입한다."""

    def __init__(self, client: Any, model: str):
        self._client = client
        self.model = model

    async def choose(self, confidence: dict[str, Any], allowed: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        bound = self._client.bind_tools(TOOLS, tool_choice="required", parallel_tool_calls=False)
        message = await bound.ainvoke([("system", SYSTEM_PROMPT), ("human", describe(confidence, allowed))])
        calls = getattr(message, "tool_calls", None) or []
        if not calls:
            raise ValueError("no_tool_call")
        call = calls[0]
        name = TOOL_NAMES.get(call.get("name"))
        if not name:
            raise ValueError("unknown_tool")
        return name, dict(call.get("args") or {})


async def assess(assessor: Assessor | None, confidence: dict[str, Any] | None,
                 history: dict[str, Any]) -> dict[str, Any]:
    """판단 결과: {"request": 화면 요청|None, "record": 기록}. 어떤 실패도 검색을 막지 않는다."""
    if not confidence or not confidence.get("low"):
        return {"request": None, "record": None}
    allowed = allowed_actions(confidence, history)
    record: dict[str, Any] = {"reasons": confidence.get("reasons"), "allowed": allowed,
                              "prompt_version": ASSESS_PROMPT_VERSION, "confidence_version": confidence.get("version")}
    if not allowed["photo"] and not allowed["fields"]:
        return {"request": None, "record": {**record, "tool": "accept_results", "source": "limit"}}
    if assessor is None:
        return {"request": None, "record": {**record, "tool": "accept_results", "source": "no_llm"}}
    try:
        name, args = await assessor.choose(confidence, allowed)
    except Exception as exc:  # LLM 실패는 결과를 그대로 보여 주는 것으로 대신한다
        log.warning("assess llm failed type=%s", type(exc).__name__)
        return {"request": None, "record": {**record, "tool": "accept_results", "source": "llm_error",
                                            "error": type(exc).__name__}}
    request = build_request(name, args, allowed)
    record.update(tool=name, source="llm", model=assessor.model,
                  args={k: v for k, v in args.items() if k in ("field",)},
                  rejected=request is None and name != "accept_results")
    return {"request": request, "record": record}
