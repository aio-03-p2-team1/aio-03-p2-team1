"""검색 에이전트: 결과가 애매할 때 LLM이 도구로 결과를 읽고(read) → 판단하고 → 조건을 고쳐 다시 찾는다(act).

그래프 안의 루프 (LangGraph 노드 2개):
    validate ─(확신 낮음)→ agent ⇄ agent_tools ─(조건 수정)→ rank 또는 radius → validate → agent …
                                     └─(요청·확정)→ locate → finalize
- agent       : LLM 한 걸음. 지금까지의 대화(도구 결과 포함)를 보고 도구 하나를 고른다(bind_tools, tool_choice=required).
- agent_tools : 고른 도구를 서버가 검증·실행한다. 읽기 도구는 결과를 돌려주고, 수정 도구는 조건을 고친 뒤 다시 검색한다.

도구
| 구분 | 도구 | 하는 일 |
| 읽기 | read_criteria   | 사용자가 쓴 원문 설명과 지금 검색 조건 |
| 읽기 | read_results    | 상위 후보 요약(품종·색·성별·특징·유사도·일치 근거). 연락처·주소 등 개인정보는 넘기지 않음 |
| 수정 | update_features | 원문 설명을 다시 해석해 털색·품종·성별·특징 조건을 고침 → 다시 정렬 |
| 수정 | relax_condition | 품종·성별 조건을 풀어 줌(설명과 맞지 않거나 너무 좁을 때) → 다시 정렬 |
| 수정 | widen_radius    | 반경 한 단계 넓힘 → 반경부터 다시 |
| 종료 | request_photo / request_info | 사용자에게 사진·정보 요청(assess.py 규칙으로 검증) |
| 종료 | finish          | 지금 결과로 확정 |

사실을 지어내지 않도록:
- LLM 출력은 도구 인자뿐이고, 서버가 모두 검증한다. update_features 값은 사용자 원문에 근거가 있어야 받는다
  (털색: 원문 색 단어와 같은 색, 품종·특징: 원문에 있는 말, 성별: 원문에 수컷/암컷 표현). 근거가 없으면 거부하고 이유를 돌려준다.
- 공고 번호·날짜·좌표·연락처는 고칠 수 있는 값이 아니다. 반경은 정해진 단계로만 움직인다.
- 단계마다 무엇을 읽고 무엇을 고쳤는지, 결과가 어떻게 바뀌었는지 agent_log 에 남긴다.
한도: LLM 걸음 최대 MAX_STEPS, 다시 찾기 최대 MAX_RERUNS. LLM 없음·실패·한도 초과면 지금 결과를 그대로 보여 준다.
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

AGENT_PROMPT_VERSION = "search-agent-v1"
MAX_STEPS = 6  # LLM 걸음(도구 선택) 최대 횟수
MAX_RERUNS = 2  # 조건을 고쳐 다시 찾는 최대 횟수
TOP_READ = 10
SEX_WORDS = {"M": ("수컷", "숫컷", "수놈", "남아", "남자아이"), "F": ("암컷", "암놈", "여아", "여자아이")}

SYSTEM_PROMPT = f"""너는 잃어버린 반려동물 검색 결과를 점검하는 에이전트다.
검색은 이미 한 번 끝났고 결과가 애매하다는 신호가 있다. 도구로 결과를 읽고, 판단하고, 필요하면 조건을 고쳐 다시 찾는다.

진행 방법:
1. read_criteria 와 read_results 로 사용자 설명과 상위 후보를 읽는다.
2. 판단한다: 사용자 설명의 털색·품종·성별·특징이 검색 조건에 제대로 들어갔는가? 상위 후보가 설명과 맞는가?
   - 설명에는 있는데 조건에 빠진 특징이 있으면 update_features 로 넣는다.
   - 품종·성별 조건 때문에 맞을 법한 후보가 밀려나면 relax_condition 으로 푼다.
   - 후보가 너무 적거나 다 맞지 않으면 widen_radius 로 반경을 넓힌다.
3. 고친 뒤에는 새 결과를 다시 읽고 이전과 비교한다. 다시 찾기는 최대 {MAX_RERUNS}번이다.
4. 더 고칠 것이 없으면 끝낸다: 결과가 그럴듯하면 finish, 글만으로 구분이 어려우면(믹스견 등) request_photo,
   받지 못한 정보가 구분에 도움이 되면 request_info.

규칙:
- 한 번에 도구 하나만 호출한다.
- 사용자 설명에 없는 특징을 만들어 넣지 않는다. 서버가 원문 근거가 없는 값은 거부한다.
- 공고 번호, 날짜, 숫자, 연락처, 보호소 이름을 지어내지 않는다.
- reason 은 사용자에게 보일 수 있는 한국어 한 문장(60자 이내), 존댓말, 숫자 없이 쓴다."""


class ReadCriteria(BaseModel):
    """사용자가 쓴 원문 설명과 지금 검색 조건(털색·품종·성별·특징·반경)을 읽는다."""


class ReadResults(BaseModel):
    """상위 후보 요약을 읽는다: 품종, 털색, 성별, 나이, 특징 글, 벡터 유사도, 일치·불일치 근거."""

    top: int = Field(5, ge=1, le=TOP_READ, description="읽을 후보 수")


class UpdateFeatures(BaseModel):
    """사용자 원문 설명을 다시 해석해 검색 조건을 고친다. 원문에 근거가 있는 값만 받는다. 고치면 다시 정렬한다."""

    colors: list[Color] | None = Field(None, description="원문에 나온 털색(표준 색 이름)")
    breed: str | None = Field(None, description="원문에 나온 품종 표현 그대로")
    sex: Literal["M", "F"] | None = Field(None, description="원문에 수컷/암컷 표현이 있을 때만")
    marks: list[str] | None = Field(None, description="원문에 나온 눈에 띄는 특징 낱말(예: 얼룩, 꼬리 짧음)")
    reason: str = Field(description="고치는 이유 한 문장")


class RelaxCondition(BaseModel):
    """품종 또는 성별 조건을 풀어 준다. 다시 정렬한다."""

    field: Literal["breed", "sex"]
    reason: str = Field(description="푸는 이유 한 문장")


class WidenRadius(BaseModel):
    """실종 위치 기준 반경을 한 단계 넓혀 다시 찾는다."""

    reason: str = Field(description="넓히는 이유 한 문장")


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


TOOLS = [ReadCriteria, ReadResults, UpdateFeatures, RelaxCondition, WidenRadius, RequestPhoto, RequestInfo, Finish]
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


def source_text(criteria: dict[str, Any]) -> str:
    """사용자가 직접 쓴 말(설명·품종·털색 입력). 에이전트가 고친 값은 근거가 될 수 없으므로 처음 값을 고정해 쓴다."""
    return " ".join(str(criteria.get(k) or "") for k in ("description", "breed", "color")).strip()


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
        "사용자_원문": state.get("agent_source") or source_text(c),
        "조건": {k: c.get(k) for k in ("species", "breed", "color", "sex", "size") if c.get(k)},
        "추가_특징": (state.get("llm_features") or {}).get("marks") or [],
        "반경_km": radius.get("radius_km") if radius.get("applied") else None,
    }


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
    breed = str(args.get("breed") or "").strip()
    if breed:
        if len(breed) >= 2 and breed.replace(" ", "") in source.replace(" ", ""):
            accepted["breed"] = breed
        else:
            rejected.append(f"품종 '{breed}': 원문에 없는 말")
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


def start_messages(state: dict[str, Any], allowed: dict[str, Any]) -> list[Any]:
    Human, System, _ = _messages()
    return [System(content=SYSTEM_PROMPT),
            Human(content="검색 결과 신호:\n" + signals_text(state.get("confidence"), state.get("radius"), 0, allowed))]


def rerun_message(state: dict[str, Any], allowed: dict[str, Any], before: dict[str, Any]) -> Any:
    Human, _, _ = _messages()
    after = _summary(state)
    changed = "바뀜" if after.get("top_id") != before.get("top_id") else "같음"
    return Human(content=(
        "다시 찾은 결과 신호:\n"
        + signals_text(state.get("confidence"), state.get("radius"), state.get("agent_reruns", 0), allowed)
        + f"\n이전 1등 유사도 {before.get('top_similarity')} → 지금 {after.get('top_similarity')}, 1등 후보 {changed}"
    ))


def execute_tool(name: str, args: dict[str, Any], state: dict[str, Any], allowed: dict[str, Any]) -> dict[str, Any]:
    """도구 하나를 서버 규칙으로 실행한다. 반환: {content(LLM에 돌려줄 결과), update(상태 변경), next, done, request, log}."""
    criteria = state["criteria"]
    reruns = state.get("agent_reruns", 0)
    out: dict[str, Any] = {"update": {}, "next": None, "done": False, "request": None}
    if name == "read_criteria":
        out["content"] = read_criteria(state)
    elif name == "read_results":
        top = args.get("top") if isinstance(args.get("top"), int) else 5
        out["content"] = read_results(state, max(1, min(top, TOP_READ)))
    elif name in ("update_features", "relax_condition", "widen_radius") and reruns >= MAX_RERUNS:
        out["content"] = {"ok": False, "error": "다시 찾기 횟수를 다 썼습니다. finish 또는 요청으로 끝내세요."}
    elif name == "update_features":
        accepted, rejected = validate_features(args, state.get("agent_source") or source_text(criteria))
        if not accepted:
            out["content"] = {"ok": False, "rejected": rejected or ["바꿀 값이 없음"]}
        else:
            new_criteria, features = dict(criteria), dict(state.get("llm_features") or {})
            if "colors" in accepted:
                new_criteria["color"] = " ".join(accepted["colors"])
            if "breed" in accepted:
                new_criteria["breed"] = accepted["breed"]
            if "sex" in accepted:
                new_criteria["sex"] = accepted["sex"]
            if "marks" in accepted:
                features["marks"] = list(dict.fromkeys([*(features.get("marks") or []), *accepted["marks"]]))
            # 검색 문장이 바뀌므로 유사도를 처음부터 다시 계산한다(semantic_scores 비움).
            out.update(update={"criteria": new_criteria, "llm_features": features, "semantic_scores": None,
                               "agent_reruns": reruns + 1}, next="rank")
            out["content"] = {"ok": True, "applied": accepted, "rejected": rejected, "다음": "다시 정렬합니다"}
    elif name == "relax_condition":
        field = args.get("field")
        features = dict(state.get("llm_features") or {})
        if field not in ("breed", "sex") or not (criteria.get(field) or features.get(field)):
            out["content"] = {"ok": False, "error": f"풀 조건이 없음: {field}"}
        else:
            new_criteria = {k: v for k, v in criteria.items() if k != field}
            features.pop(field, None)
            out.update(update={"criteria": new_criteria, "llm_features": features, "semantic_scores": None,
                               "agent_reruns": reruns + 1}, next="rank")
            out["content"] = {"ok": True, "relaxed": field, "다음": "다시 정렬합니다"}
    elif name == "widen_radius":
        radius = state.get("radius") or {}
        step, max_step = radius.get("step"), radius.get("max_step")
        if not radius.get("applied") or not isinstance(step, int) or not isinstance(max_step, int) or step >= max_step:
            out["content"] = {"ok": False, "error": "반경을 더 넓힐 수 없음"}
        else:
            # 공고는 이미 받아 두었으므로 반경 계산부터 다시 한다(API 재호출 없음).
            out.update(update={"criteria": {**criteria, "radius_step": step + 1}, "agent_reruns": reruns + 1},
                       next="radius")
            out["content"] = {"ok": True, "radius_step": step + 1, "다음": "반경을 넓혀 다시 찾습니다"}
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
    keep = {k: v for k, v in args.items() if k in ("top", "colors", "breed", "sex", "marks", "field")}
    for k in ("reason", "note"):
        if args.get(k):
            keep[k] = str(args[k])[:80]
    return keep
