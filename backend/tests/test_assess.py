"""assess 노드: 확신 신호 → LLM 도구 선택 → 서버 검증 → 반복 제한. LLM은 가짜 client(실제 호출 아님)."""

import asyncio

from backend.agent import assess as A
from backend.agent.ranking import confidence_signals

from .test_graph import START, deps, search


class FakeToolMessage:
    def __init__(self, calls):
        self.tool_calls = calls


class FakeToolClient:
    """LangChain bind_tools → ainvoke 흉내. 고를 도구를 미리 정해 둔다."""

    def __init__(self, name="RequestPhoto", args=None, error=None):
        self.name, self.args, self.error = name, args or {"reason": "사진을 올려 주세요."}, error
        self.bound = None
        self.messages = []

    def bind_tools(self, tools, **options):
        self.bound = ([t.__name__ for t in tools], options)
        return self

    async def ainvoke(self, messages):
        self.messages.append(messages)
        if self.error:
            raise self.error
        return FakeToolMessage([{"name": self.name, "args": self.args, "id": "call_1"}] if self.name else [])


LOW = {"low": True, "reasons": ["mixed_breed"], "version": "t",
       "signals": {"color_given": True, "breed_mixed": True, "photo_given": False}}


def run(coro):
    return asyncio.run(coro)


def test_confidence_low_for_mixed_breed_without_photo():
    cands = [{"semantic_score": 0.8, "evidence": {"matched": ["털색"]}}, {"semantic_score": 0.6}]
    conf = confidence_signals(cands, {"description": "믹스견 하얀색 엉덩이에 얼룩"})
    assert conf["low"] and "mixed_breed" in conf["reasons"]
    photo = confidence_signals(cands, {"description": "사진에서 확인한 특징: 믹스견, 흰색\n엉덩이 얼룩"})
    assert "mixed_breed" not in photo["reasons"]  # 사진을 이미 줬으면 믹스견 사유로 다시 요청하지 않음


def test_confidence_not_low_when_specific_and_matching():
    cands = [{"semantic_score": 0.8, "evidence": {"matched": ["품종", "털색"]}}, {"semantic_score": 0.5}]
    conf = confidence_signals(cands, {"description": "시바 검정색 수컷", "sex": "M"}, {"breed": "시바"})
    assert conf["low"] is False and conf["reasons"] == []


def test_llm_picks_photo_and_tools_are_bound_once_required():
    client = FakeToolClient()
    out = run(A.assess(A.Assessor(client, "m"), LOW, {}))
    assert out["request"] == {"type": "photo", "reason": "사진을 올려 주세요."}
    assert client.bound == (["RequestPhoto", "RequestInfo", "AcceptResults"],
                            {"tool_choice": "required", "parallel_tool_calls": False})
    assert out["record"]["tool"] == "request_photo" and out["record"]["prompt_version"] == A.ASSESS_PROMPT_VERSION
    human = client.messages[0][1][1]
    assert "허용 행동: request_photo, request_info(field: size|sex|marks), accept_results" in human  # 털색은 이미 받음


def test_info_options_come_from_server_and_numbers_in_reason_replaced():
    client = FakeToolClient("RequestInfo", {"field": "size", "reason": "공고 4411000-2026 과 비슷해요", "options": ["거대"]})
    out = run(A.assess(A.Assessor(client, "m"), LOW, {}))
    assert out["request"]["options"] == A.FIELD_OPTIONS["size"]  # LLM이 만든 보기는 무시
    assert out["request"]["reason"] == A.DEFAULT_REASON["size"]  # 숫자 포함 문장은 고정 문구로


def test_disallowed_field_or_unknown_tool_means_no_request():
    out = run(A.assess(A.Assessor(FakeToolClient("RequestInfo", {"field": "color", "reason": "x"}), "m"), LOW, {}))
    assert out["request"] is None and out["record"]["rejected"] is True  # 털색은 이미 받은 정보
    out = run(A.assess(A.Assessor(FakeToolClient("delete_db", {}), "m"), LOW, {}))
    assert out["request"] is None and out["record"]["source"] == "llm_error"


def test_llm_absent_or_failing_shows_results_without_request():
    assert run(A.assess(None, LOW, {}))["record"]["source"] == "no_llm"
    out = run(A.assess(A.Assessor(FakeToolClient(error=TimeoutError()), "m"), LOW, {}))
    assert out["request"] is None and out["record"]["tool"] == "accept_results"
    assert run(A.assess(A.Assessor(FakeToolClient(name=None), "m"), LOW, {}))["record"]["source"] == "llm_error"


def test_repeat_limits_and_declined():
    used = {"photo_requests": 1, "info_requests": 2, "asked_fields": ["size", "sex"]}
    out = run(A.assess(A.Assessor(FakeToolClient(), "m"), LOW, used))
    assert out["request"] is None and out["record"]["source"] == "limit"
    allowed = A.allowed_actions(LOW, {"declined": ["photo", "size"], "asked_fields": ["sex"]})
    assert allowed == {"photo": False, "fields": ["marks"]}


def test_graph_runs_assess_and_thread_remembers_requests():
    d = {**deps(), "assessor": A.Assessor(FakeToolClient(), "m")}
    first = search(d, {"species": "dog", "region": "전체", "lost_date": START, "description": "믹스견 흰색"})
    assert first["status"] == "completed" and first["candidates"]  # 요청이 있어도 결과는 그대로
    assert first["agent_request"]["type"] == "photo"
    assert any(c["tool"] == "agent_assess" for c in first["tool_calls"])
    # 같은 대화에서 사진은 한 번만 요청한다(LLM이 또 골라도 서버가 막음).
    again = search(d, {"description": "믹스견 흰색 꼬리 짧음"}, thread_id=first["thread_id"])
    assert again["agent_request"] is None and again["agent_decision"]["allowed"]["photo"] is False


def test_declined_field_not_asked_again_via_api_body():
    d = {**deps(), "assessor": A.Assessor(FakeToolClient("RequestInfo", {"field": "size", "reason": "크기를 알려 주세요."}), "m")}
    run_ = search(d, {"species": "dog", "region": "전체", "lost_date": START, "description": "믹스견 흰색"},
                  declined=["size"])
    assert run_["agent_request"] is None and "size" not in run_["agent_decision"]["allowed"]["fields"]
