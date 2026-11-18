"""검색 에이전트: 정상 검색마다 LLM이 결과를 읽고 → 판단하고 → 필요하면 조건을 고쳐 다시 찾는다.

그래프 안의 루프 (LangGraph 노드 2개):
    validate ─(빈 결과 포함)→ agent ⇄ agent_tools ─(조건 수정)→ rank 또는 radius → validate → agent …
                                     └─(요청·확정)→ locate → finalize
- agent       : LLM 한 걸음. 지금까지의 대화(결과·도구 결과 포함)를 보고 도구 하나를 고른다(bind_tools, tool_choice=required).
- agent_tools : 고른 도구를 서버가 검증·실행한다. 수정 도구는 조건을 고친 뒤 다시 검색한다.

읽기: 별도 읽기 도구를 부르면 LLM 호출이 늘어나므로, 처음 메시지와 다시 찾은 뒤 메시지에
      사용자 원문·현재 조건·상위 후보 요약(품종·색·성별·특징·유사도·일치 근거)을 서버가 미리 넣어 준다.
      공고 번호·날짜·연락처·주소는 넣지 않는다.

도구
| 구분 | 도구 | 하는 일 |
| 수정 | update_features | 원문 설명을 다시 해석해 털색·성별·특징을 '추출 특징'에 보강 → 다시 정렬(검색 조건은 바꾸지 않음) |
| 질문 | relax_condition | 성별 조건을 빼자고 사용자에게 묻는다(사용자 동의 전에는 조건 유지). 품종은 묻지도 풀지도 않음 |
| 질문 | widen_radius    | 반경을 한 단계 넓힐지 사용자에게 묻는다(동의하면 다음 검색에서 넓힘) |
| 재검색 | search_notices | 같은 조건의 다음 페이지 실제 조회, 지역 확대는 사용자 확인 질문 |
| 종료 | request_photo / request_info | 사용자에게 사진·정보 요청(assess.py 규칙으로 검증) |
| 종료 | finish          | 지금 결과로 확정 |

사실을 지어내지 않도록:
- LLM 출력은 도구 인자뿐이고, 서버가 모두 검증한다. update_features 값은 사용자 원문에 근거가 있어야 받는다
  (털색: 원문 색 단어와 같은 색, 특징: 원문에 있는 말, 성별: 원문에 수컷/암컷 표현). 근거가 없으면 거부하고 이유를 돌려준다.
- 공고 번호·날짜·좌표·연락처는 고칠 수 있는 값이 아니다. 반경은 정해진 단계로만 움직인다.
- 단계마다 무엇을 읽고 무엇을 고쳤는지, 결과가 어떻게 바뀌었는지 agent_log 에 남긴다.
한도: LLM 걸음 최대 MAX_STEPS, 다시 찾기 최대 MAX_RERUNS, 실제 재조회 최대 MAX_RESEARCHES.
지역 확대는 사용자 후속 입력을 기다린다. LLM 없음·실패·한도 초과면 지금 결과를 그대로 보여 준다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.agent import assess as rules
from backend.agent.color_tokenizer import tokenize_color_words
from backend.schemas.common import Color

log = logging.getLogger("dasimanna.agent")

AGENT_PROMPT_VERSION = "search-agent-v5"
MAX_STEPS = 4  # LLM 걸음(도구 선택) 최대 횟수. 흔한 흐름은 수정 1번 + 종료 1번 = 2걸음
MAX_RERUNS = 2  # 조건을 고쳐 다시 찾는 최대 횟수
MAX_RESEARCHES = 1  # 최초 조회 외 실제 공고 API 재조회 최대 횟수(통신 재시도와 구분)
TOP_READ = 5  # LLM에 보여 줄 상위 후보 수
SEX_WORDS = {"M": ("수컷", "숫컷", "수놈", "남아", "남자아이"), "F": ("암컷", "암놈", "여아", "여자아이")}

SYSTEM_PROMPT = f"""너는 잃어버린 반려동물 검색 결과를 점검하는 에이전트다.
검색은 이미 한 번 끝났다. 후보가 충분한 검색과 후보가 없는 검색도 모두 검토한다.
메시지에 사용자 원문, 현재 조건·추출 특징, 단계별 조회·필터 건수, 상위 후보 요약이 들어 있다.
그것을 읽고 판단하고, 필요하면 도구로 조건을 고쳐 다시 찾는다.

진행 방법:
1. 메시지의 사용자 원문과 상위 후보를 읽는다.
2. 판단한다: 사용자 설명의 털색·성별·특징이 검색 조건에 제대로 들어갔는가? 상위 후보가 설명과 맞는가?
   - 확신 충분이면 원문에 근거한 명백한 오류가 없는 한 finish 한다. 사진·추가 정보는 요청하지 않는다.
   - 설명에는 있는데 조건과 추출 특징 모두에 빠진 특징이 있으면 update_features 로 추출 특징에 넣는다.
     추출 특징에 이미 있는 털색·성별·특징을 빠진 정보로 취급하지 않는다.
   - 사용자가 고른 검색 조건(종류·지역·기간·품종·털색·성별·크기·반경)은 네가 바꾸지 않는다.
     조건을 바꿔야 할 것 같으면 바꾸지 말고 사용자에게 묻는다: 성별 조건은 relax_condition, 반경은 widen_radius,
     지역은 search_notices(action=widen_region). 이 셋은 질문만 하고 끝난다. 사용자가 동의하면 다음 검색에서 바뀐다.
   - 품종은 사용자가 고른 그대로 둔다. 품종을 풀거나 바꾸자고 묻지 않는다.
   - 후보가 없으면 검색_단계의 빈_결과_원인을 먼저 확인한다.
     원본_공고_없음이면 재정렬로 새 공고가 생기지 않는다.
     다음 페이지가 남으면 search_notices(action=next_page)로 같은 조건의 공고를 더 조회할 수 있다.
     다른 지역 조회가 필요하면 search_notices(action=widen_region)로 묻는다.
     반경_필터이면 widen_radius 로 묻는다.
     선택 가능한 재검색·질문이 없으면 도움이 되는 정보 요청 또는 finish 를 선택한다.
   - 검색_단계의 선택_가능_재검색에 있는 action만 고른다. 실제 재조회는 최대 {MAX_RESEARCHES}번이다.
   - 원인과 근거를 보고 재정렬·같은 조건 재조회·범위 확대 질문·추가 정보 요청·종료 중 전략을 선택한다.
     중복 제거·공식 코드 검증은 서버가 처리한다. 별도 성찰 모델을 부르지 않는다.
3. 고친 뒤에는 새 결과 메시지를 읽고 이전과 비교한다. 다시 찾기는 최대 {MAX_RERUNS}번이다.
4. 더 고칠 것이 없으면 끝낸다: 결과가 그럴듯하면 finish, 글만으로 구분이 어려우면(믹스견 등) request_photo,
   받지 못한 정보가 구분에 도움이 되면 request_info.

규칙:
- 한 번에 도구 하나만 호출한다.
- 도구로 고칠 필요가 없으면 finish 한다. 개입을 늘리려고 조건을 바꾸거나 정보를 요청하지 않는다.
- 사용자 설명에 없는 특징을 만들어 넣지 않는다. 서버가 원문 근거가 없는 값은 거부한다.
- 공고 번호, 날짜, 숫자, 연락처, 보호소 이름을 지어내지 않는다.
- reason 은 사용자에게 보일 수 있는 한국어 한 문장(60자 이내), 존댓말, 숫자 없이 쓴다."""


class UpdateFeatures(BaseModel):
    """사용자 원문 설명을 다시 해석해 추출 특징을 보강한다. 원문에 근거가 있는 값만 받는다. 검색 조건은 바꾸지 않는다. 고치면 다시 정렬한다."""

    colors: list[Color] | None = Field(None, description="원문에 나온 털색(표준 색 이름)")
    sex: Literal["M", "F"] | None = Field(None, description="원문에 수컷/암컷 표현이 있을 때만")
    marks: list[str] | None = Field(None, description="원문에 나온 눈에 띄는 특징 낱말(예: 얼룩, 꼬리 짧음)")
    reason: str = Field(description="고치는 이유 한 문장")


class RelaxCondition(BaseModel):
    """사용자가 고른 성별 조건을 빼고 다시 찾을지 사용자에게 묻는다(질문만 하고 끝남). 품종은 대상이 아니다."""

    field: Literal["sex"]
    reason: str = Field(description="묻는 이유 한 문장")


class WidenRadius(BaseModel):
    """실종 위치 기준 반경을 한 단계 넓혀 다시 찾을지 사용자에게 묻는다(질문만 하고 끝남)."""

    reason: str = Field(description="묻는 이유 한 문장")


class SearchNotices(BaseModel):
    """부족한 공고를 실제 API에서 추가 조회하거나, 전체 지역 확대의 사용자 동의를 요청한다."""

    action: Literal["next_page", "widen_region"] = Field(
        description="next_page: 같은 조건 조회의 다음 페이지. widen_region: 지역 확대 동의 요청만(질문)")
    reason: str = Field(description="관찰한 문제와 선택한 전략의 이유 한 문장")


class RequestPhoto(BaseModel):
    """사용자에게 사진을 요청하고 끝낸다. 사진에서 특징을 뽑아 다시 검색하게 된다."""

    reason: str = Field(description="사용자에게 보일 요청 이유 한 문장(숫자·날짜·번호 금지)")


class RequestInfo(BaseModel):
    """사용자에게 정보 하나를 버튼으로 묻고 끝낸다. 보기는 서버가 정한다."""

    field: Literal["color", "size", "sex", "marks"]
    reason: str = Field(description="사용자에게 보일 요청 이유 한 문장(숫자·날짜·번호 금지)")


class Finish(BaseModel):
    """지금 결과로 확정하고 끝낸다."""

    note: str = Field(description="판단 이유 한 문장(기록용)")


TOOLS = [UpdateFeatures, RelaxCondition, WidenRadius, SearchNotices, RequestPhoto, RequestInfo, Finish]
TOOL_NAMES = {cls.__name__: re.sub(r"(?<!^)([A-Z])", r"_\1", cls.__name__).lower() for cls in TOOLS}
TOOL_NAMES.update({v: v for v in list(TOOL_NAMES.values())})
END_TOOLS = {"request_photo", "request_info", "finish"}


class SearchAgent:
    """LangChain 채팅 모델에 도구를 묶어 한 걸음씩 부른다. 시험에서는 가짜 client 를 주입한다."""

    def __init__(self, client: Any, model: str):
        self._client = client
        self.model = model
        self._bound = None

    async def step(self, messages: list[Any]) -> Any:
        if self._bound is None:
            self._bound = self._client.bind_tools(TOOLS, tool_choice="required", parallel_tool_calls=False)
        return await self._bound.ainvoke(messages)


def _messages():
    # langchain_core 는 langchain-openai 의존성으로 함께 설치된다. 시험에서도 같은 메시지 클래스를 쓴다.
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

    return HumanMessage, SystemMessage, ToolMessage


def source_text(criteria: dict[str, Any], photo: dict[str, Any] | None = None) -> str:
    """수정 값의 근거가 되는 말: 사용자가 직접 쓴 말(설명·품종·털색 입력) + 쓸 만한 사진에서 서버가 확인한 특징.

    에이전트가 고친 값은 근거가 될 수 없으므로 처음 값을 고정해 쓴다.
    """
    text = " ".join(str(criteria.get(k) or "") for k in ("description", "breed", "color")).strip()
    if photo and photo.get("suitable"):
        traits = [*(photo.get("colors") or []), photo.get("breed") or "", *(photo.get("marks") or [])]
        sex = {"M": "수컷", "F": "암컷"}.get(photo.get("sex") or "")
        text = " ".join([text, *[t for t in traits if t], sex or ""]).strip()
    return text


def signals_text(confidence: dict[str, Any] | None, radius: dict[str, Any] | None, reruns: int,
                 allowed: dict[str, Any]) -> str:
    conf = confidence or {}
    s = conf.get("signals") or {}
    radius = radius or {}
    lines = [
        "애매한 이유: " + (", ".join(rules.REASON_LABELS.get(r, r) for r in conf.get("reasons") or []) or "없음(확신 충분)"),
        f"후보 수: {s.get('candidates')}, 1등 유사도: {s.get('top_similarity')}, 1·2등 차이: {s.get('similarity_gap')}",
        (f"반경: {radius.get('radius_km')}km (단계 {radius.get('step')}/{radius.get('max_step')})"
         if radius.get("applied") else "반경: 적용 안 됨(넓히기 불가)"),
        f"남은 다시 찾기: {MAX_RERUNS - reruns}회",
        "끝낼 때 고를 수 있는 요청: "
        + (", ".join((["request_photo"] if allowed["photo"] else [])
                     + ([f"request_info(field: {'|'.join(allowed['fields'])})"] if allowed["fields"] else []))
           or "없음(finish 만 가능)"),
    ]
    return "\n".join(lines)


def read_criteria(state: dict[str, Any]) -> dict[str, Any]:
    c = state["criteria"]
    radius = state.get("radius") or {}
    return {
        "사용자_원문": state.get("agent_source") or source_text(c, state.get("photo_features")),
        "조건": {k: c.get(k) for k in ("species", "breed", "color", "sex", "size") if c.get(k)},
        "추가_특징": (state.get("llm_features") or {}).get("marks") or [],
        "추출_특징": {k: v for k, v in (state.get("llm_features") or {}).items()
                     if k in ("colors", "sex", "marks") and v},
        "사진": _photo_summary(state.get("photo_features")),
        "반경_km": radius.get("radius_km") if radius.get("applied") else None,
        # 사용자가 직접 고르거나 질문에 답한 조건. 에이전트는 이 값을 바꾸지 않는다(바꿔야 하면 묻는다).
        "사용자가_고른_조건": sorted(k for k, o in ((state.get("context_summary") or {}).get("origin") or {}).items()
                                if o in ("request", "session") and k in USER_CONDITION_KEYS and c.get(k) not in (None, "")),
        "재질문_답변": answered_values(state),
    }


USER_CONDITION_KEYS = {"species", "region", "start_date", "end_date", "breed", "color", "sex", "size", "radius_step"}


def answered_values(state: dict[str, Any]) -> dict[str, Any]:
    """앞선 질문(사진·정보 요청, 범위 넓히기)에 사용자가 답해 지금 조건에 들어간 값."""
    c = state["criteria"]
    history = state.get("agent_history") or {}
    asked = set(history.get("asked_fields") or []) | set(history.get("confirmed_fields") or [])
    keys = {"radius": "radius_step"}
    out = {keys.get(k, k): c.get(keys.get(k, k)) for k in sorted(asked) if c.get(keys.get(k, k)) not in (None, "")}
    for field in history.get("relaxed_fields") or []:
        out[field] = "조건 빼기에 동의"
    return out


def _photo_summary(photo: dict[str, Any] | None) -> dict[str, Any] | str:
    if not photo:
        return "받지 않음"
    if not photo.get("suitable"):
        return "받았지만 쓸 수 없는 사진(동물이 잘 보이지 않음)"
    return {k: photo.get(k) for k in ("species", "breed", "colors", "sex", "marks") if photo.get(k)}


def read_results(state: dict[str, Any], top: int) -> list[dict[str, Any]]:
    """후보 요약. 보호소 연락처·주소·공고 번호·날짜는 넘기지 않는다(LLM이 그대로 옮겨 적지 못하게)."""
    out = []
    for c in (state.get("candidates") or [])[:top]:
        ev = c.get("evidence") or {}
        out.append({
            "순위": c.get("rank"), "품종": c.get("breed"), "털색": c.get("color"), "성별": c.get("sex"),
            "나이": c.get("age"), "특징": (c.get("special_mark") or "")[:80],
            "유사도": round(c["semantic_score"], 3) if isinstance(c.get("semantic_score"), (int, float)) else None,
            "일치": ev.get("matched") or [], "불일치": ev.get("mismatched") or [], "미확인": ev.get("unknown") or [],
        })
    return out


def validate_features(args: dict[str, Any], source: str) -> tuple[dict[str, Any], list[str]]:
    """update_features 인자를 원문 근거로 검증한다. (받은 값, 거부 이유 목록)."""
    accepted: dict[str, Any] = {}
    rejected: list[str] = []
    src_tokens = tokenize_color_words(source)
    src_colors = src_tokens["colors"] | src_tokens["patterns"]
    colors = []
    for color in args.get("colors") or []:
        tokens = tokenize_color_words(color)
        if (tokens["colors"] | tokens["patterns"]) and (tokens["colors"] | tokens["patterns"]) <= src_colors:
            colors.append(color)
        else:
            rejected.append(f"털색 '{color}': 원문에 같은 색 표현이 없음")
    if colors:
        accepted["colors"] = list(dict.fromkeys(colors))
    sex = args.get("sex")
    if sex in SEX_WORDS:
        if any(w in source for w in SEX_WORDS[sex]):
            accepted["sex"] = sex
        else:
            rejected.append("성별: 원문에 수컷/암컷 표현이 없음")
    marks = []
    for mark in (args.get("marks") or [])[:5]:
        mark = str(mark).strip()
        if 2 <= len(mark) <= 10 and mark.replace(" ", "") in source.replace(" ", ""):
            marks.append(mark)
        elif mark:
            rejected.append(f"특징 '{mark}': 원문에 없는 말")
    if marks:
        accepted["marks"] = list(dict.fromkeys(marks))
    return accepted, rejected


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _summary(state: dict[str, Any]) -> dict[str, Any]:
    conf = state.get("confidence") or {}
    s = conf.get("signals") or {}
    top = (state.get("candidates") or [{}])[0] if state.get("candidates") else {}
    return {"low": conf.get("low"), "reasons": conf.get("reasons") or [], "candidates": s.get("candidates"),
            "top_similarity": s.get("top_similarity"), "top_id": top.get("id"),
            "top_matched": len((top.get("evidence") or {}).get("matched") or [])}


def research_options(state: dict[str, Any]) -> list[str]:
    """서버가 실제 조회 범위·확신·한도로 허용하는 전략만 제공한다."""
    if state.get("error") or ((state.get("confidence") or {}).get("low") is False and state.get("candidates")):
        return []
    query = state.get("search_query") or {}
    if not query:
        return []
    options = []
    if state.get("agent_researches", 0) < MAX_RESEARCHES and state.get("agent_reruns", 0) < MAX_RERUNS:
        if state.get("pages_fetched", 0) > 0 and state.get("total_count", 0) > len(state.get("raw_items") or []):
            options.append("next_page")
    # 확인 요청 자체는 새 API를 호출하지 않는다. 실제 범위 변경은 사용자 후속 입력만 받는다.
    if state["criteria"].get("region") not in (None, "all") and query.get("region_code"):
        options.append("widen_region")
    return options


def search_summary(state: dict[str, Any]) -> dict[str, Any]:
    """조회와 필터를 구분한다. API 실패는 이 검토 경로에 들어오지 않는다."""
    raw = state.get("raw_items") or []
    radius_items = state.get("radius_items")
    after_radius = radius_items if radius_items is not None else raw
    candidates = state.get("candidates") or []
    cause = None
    if not candidates:
        cause = "원본_공고_없음" if not raw else ("반경_필터" if not after_radius else "조건_필터")
    return {"조회_총건수": state.get("total_count", 0), "받은_공고": len(raw),
            "반경_필터_후": len(after_radius), "조건_필터_후": len(candidates), "빈_결과_원인": cause,
            "API_품종_필터": bool((state.get("search_query") or {}).get("kind")),
            "받은_페이지": state.get("pages_fetched", 0), "선택_가능_재검색": research_options(state),
            "실제_재조회_남은": max(0, MAX_RESEARCHES - state.get("agent_researches", 0))}


def context_text(state: dict[str, Any]) -> str:
    """LLM에 미리 넣어 주는 읽을거리: 사용자 원문·현재 조건·상위 후보 요약(읽기 도구 호출을 줄이려고)."""
    return ("\n사용자 원문과 현재 조건:\n" + _json(read_criteria(state))
            + "\n검색_단계:\n" + _json(search_summary(state))
            + f"\n상위 후보 {TOP_READ}개:\n" + _json(read_results(state, TOP_READ)))


def start_messages(state: dict[str, Any], allowed: dict[str, Any]) -> list[Any]:
    Human, System, _ = _messages()
    return [System(content=SYSTEM_PROMPT),
            Human(content="검색 결과 신호:\n" + signals_text(state.get("confidence"), state.get("radius"), 0, allowed)
                  + context_text(state))]


def rerun_message(state: dict[str, Any], allowed: dict[str, Any], before: dict[str, Any]) -> Any:
    Human, _, _ = _messages()
    after = _summary(state)
    changed = "바뀜" if after.get("top_id") != before.get("top_id") else "같음"
    return Human(content=(
        "다시 찾은 결과 신호:\n"
        + signals_text(state.get("confidence"), state.get("radius"), state.get("agent_reruns", 0), allowed)
        + f"\n이전 1등 유사도 {before.get('top_similarity')} → 지금 {after.get('top_similarity')}, 1등 후보 {changed}"
        + context_text(state)
    ))


def execute_tool(name: str, args: dict[str, Any], state: dict[str, Any], allowed: dict[str, Any]) -> dict[str, Any]:
    """도구 하나를 서버 규칙으로 실행한다. 반환: {content(LLM에 돌려줄 결과), update(상태 변경), next, done, request, log}."""
    criteria = state["criteria"]
    reruns = state.get("agent_reruns", 0)
    out: dict[str, Any] = {"update": {}, "next": None, "done": False, "request": None}
    if name == "update_features" and reruns >= MAX_RERUNS:
        out["content"] = {"ok": False, "error": "다시 찾기 횟수를 다 썼습니다. finish 또는 요청으로 끝내세요."}
    elif name == "update_features":
        accepted, rejected = validate_features(args, state.get("agent_source") or source_text(criteria, state.get("photo_features")))
        # 사용자가 고른 조건과 다른 값은 받지 않는다(조건을 바꾸지 않음).
        if "sex" in accepted and criteria.get("sex") and accepted["sex"] != criteria["sex"]:
            accepted.pop("sex")
            rejected.append("사용자가 고른 성별과 다름")
        if not accepted:
            out["content"] = {"ok": False, "rejected": rejected or ["바꿀 값이 없음"]}
        else:
            # 검색 조건(criteria)은 그대로 두고 추출 특징만 보강한다. 정렬은 조건+특징을 함께 본다.
            features = dict(state.get("llm_features") or {})
            if "colors" in accepted:
                features["colors"] = list(dict.fromkeys([*(features.get("colors") or []), *accepted["colors"]]))
            if "sex" in accepted:
                features["sex"] = accepted["sex"]
            if "marks" in accepted:
                features["marks"] = list(dict.fromkeys([*(features.get("marks") or []), *accepted["marks"]]))
            # 검색 문장이 바뀌므로 유사도를 처음부터 다시 계산한다(semantic_scores 비움).
            out.update(update={"llm_features": features, "semantic_scores": None,
                               "agent_reruns": reruns + 1}, next="rank")
            out["content"] = {"ok": True, "applied": accepted, "rejected": rejected, "다음": "다시 정렬합니다"}
    elif name == "relax_condition":
        field = args.get("field")
        features = dict(state.get("llm_features") or {})
        if field != "sex":
            out["content"] = {"ok": False, "error": "품종은 사용자가 고른 그대로 둡니다. 품종 조건은 풀거나 묻지 않습니다."}
        elif criteria.get("sex"):
            # 사용자가 고른 성별: 바꾸지 않고 묻는다. 동의하면 다음 검색 요청에서 조건이 빠진다.
            label = {"M": "수컷", "F": "암컷"}.get(criteria["sex"], criteria["sex"])
            out.update(done=True, next="ask", update={"questions": [{
                "field": "sex", "action": "relax",
                "message": f"성별을 '{label}'으로 찾았는데 맞는 후보가 적어요. 공고의 성별 기록이 다를 수 있어요. 성별 조건을 빼고 다시 찾아볼까요?",
            }]}, content={"ok": True, "requires_confirmation": True, "다음": "사용자가 동의하면 성별 조건을 빼고 새로 찾습니다"})
        elif features.get("sex"):
            # 사용자가 고른 조건이 아니라 설명에서 추출한 특징이면 특징에서만 뺀다.
            features.pop("sex", None)
            out.update(update={"llm_features": features, "semantic_scores": None, "agent_reruns": reruns + 1}, next="rank")
            out["content"] = {"ok": True, "relaxed": "추출_특징.sex", "다음": "다시 정렬합니다"}
        else:
            out["content"] = {"ok": False, "error": "풀 성별 조건이 없음"}
    elif name == "widen_radius":
        radius = state.get("radius") or {}
        step, max_step = radius.get("step"), radius.get("max_step")
        if not radius.get("applied") or not isinstance(step, int) or not isinstance(max_step, int) or step >= max_step:
            out["content"] = {"ok": False, "error": "반경을 더 넓힐 수 없음"}
        else:
            # 반경은 사용자가 고른 검색 범위다. 바꾸지 않고 묻는다(화면의 '넓혀 찾기' 버튼).
            nxt = radius.get("next_radius_km")
            wider = f"반경 {nxt:g}km" if isinstance(nxt, (int, float)) else "조회 지역 전체"
            out.update(done=True, next="ask", update={"questions": [{
                "field": "radius", "next_step": step + 1,
                "message": f"지금 반경 안의 후보가 적거나 맞지 않아요. 동물이 더 멀리 이동했을 수 있어요. {wider}로 넓혀 다시 찾아볼까요?",
            }]}, content={"ok": True, "requires_confirmation": True, "다음": "사용자가 동의하면 반경을 넓혀 새로 찾습니다"})
    elif name == "search_notices":
        action = args.get("action")
        if action not in research_options(state):
            out["content"] = {"ok": False, "error": "허용되지 않은 재검색 전략입니다. 선택 가능한 재검색과 한도를 확인하세요."}
        elif action == "widen_region":
            out.update(done=True, next="ask", update={"questions": [{
                "field": "region",
                "message": "현재 조회 지역 밖에 구조된 공고가 있을 수 있어요. 전체 지역으로 넓혀 다시 찾아볼까요?",
            }]}, content={"ok": True, "requires_confirmation": True, "다음": "사용자가 지역 확대를 확인하면 새로 조회합니다"})
        else:
            query = dict(state["search_query"])
            criteria, features = dict(criteria), dict(state.get("llm_features") or {})
            page = state.get("pages_fetched", 1) + 1
            # 성공하기 전에는 원래 조건·후보를 보존한다. API 실패를 빈 결과로 덮지 않는다.
            out.update(update={"agent_search_plan": {"action": action, "query": query, "page": page,
                                                       "criteria": criteria, "features": features},
                               "agent_researches": state.get("agent_researches", 0) + 1,
                               "agent_reruns": reruns + 1}, next="research")
            out["content"] = {"ok": True, "strategy": action, "다음": "공고 API를 실제로 재조회합니다"}
    elif name in ("request_photo", "request_info"):
        request = rules.build_request(name, args, allowed)
        if request is None:
            out["content"] = {"ok": False, "error": "허용되지 않은 요청입니다. 신호의 '고를 수 있는 요청'을 보세요."}
        else:
            out.update(done=True, request=request, content={"ok": True})
    elif name == "finish":
        out.update(done=True, content={"ok": True})
    else:
        out["content"] = {"ok": False, "error": f"모르는 도구: {name}"}
    return out


def safe_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """기록용 인자. 사용자에게 보일 수 있는 문장은 길이만 제한해 남긴다."""
    keep = {k: v for k, v in args.items() if k in ("colors", "sex", "marks", "field", "action")}
    for k in ("reason", "note"):
        if args.get(k):
            keep[k] = str(args[k])[:80]
    return keep
