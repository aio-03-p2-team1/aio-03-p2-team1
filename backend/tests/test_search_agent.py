"""검색 에이전트 루프: 읽기 → 판단 → 조건 수정 → 다시 찾기 → 종료. LLM은 가짜 client(실제 호출 아님)."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.agent import search_agent as SA
from backend.agent.ranking import confidence_signals

from .test_graph import START, deps, search

MIXED = {"species": "dog", "region": "전체", "lost_date": START, "description": "믹스견 흰색 엉덩이 얼룩"}


class FakeAgentClient:
    """bind_tools → ainvoke 흉내. 정해 둔 순서대로 도구를 고르고, 다 쓰면 Finish 를 고른다."""

    def __init__(self, script=(), error=None):
        self.script, self.error = list(script), error
        self.calls, self.bound = [], None

    def bind_tools(self, tools, **options):
        self.bound = ([t.__name__ for t in tools], options)
        return self

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        if self.error:
            raise self.error
        name, args = self.script.pop(0) if self.script else ("Finish", {"note": "충분함"})
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{len(self.calls)}"}])


def agent_deps(script=(), **kw):
    client = FakeAgentClient(script, **kw)
    return {**deps(), "search_agent": SA.SearchAgent(client, "fake-model")}, client


def tools_used(run):
    return [entry["tool"] for entry in run["agent_decision"]["log"] if "tool" in entry]


def test_confidence_low_for_mixed_breed_without_photo():
    cands = [{"semantic_score": 0.8, "evidence": {"matched": ["털색"]}}, {"semantic_score": 0.6}]
    assert "mixed_breed" in confidence_signals(cands, {"description": "믹스견 하얀색 엉덩이에 얼룩"})["reasons"]
    photo = confidence_signals(cands, {"description": "사진에서 확인한 특징: 믹스견, 흰색\n엉덩이 얼룩"})
    assert "mixed_breed" not in photo["reasons"]


def test_feature_updates_need_evidence_in_user_text():
    source = "믹스견 하얀색 엉덩이에 얼룩 수컷"
    accepted, rejected = SA.validate_features(
        {"colors": ["흰색", "검정"], "breed": "말티즈", "sex": "F", "marks": ["얼룩", "꼬리 짧음"]}, source)
    assert accepted == {"colors": ["흰색"], "marks": ["얼룩"]}
    assert len(rejected) == 4  # 검정·말티즈·암컷·꼬리 짧음은 원문에 없음
    accepted, _ = SA.validate_features({"breed": "믹스견", "sex": "M"}, source)
    assert accepted == {"breed": "믹스견", "sex": "M"}


def test_read_results_hides_contacts_ids_and_dates():
    state = {"candidates": [{"id": "4411", "notice_no": "경기-1", "rank": 1, "breed": "믹스견", "color": "흰색",
                             "happen_date": "2026-11-10", "care": {"tel": "010-0000-0000"}, "semantic_score": 0.71234,
                             "evidence": {"matched": ["털색: 흰색"]}}]}
    row = SA.read_results(state, 5)[0]
    assert len(SA.TOOLS) == 6  # 읽기는 메시지로 주고 도구로 부르지 않음
    assert set(row) == {"순위", "품종", "털색", "성별", "나이", "특징", "유사도", "일치", "불일치", "미확인"}
    assert row["유사도"] == 0.712


def test_agent_reads_updates_reruns_and_finishes():
    d, client = agent_deps([
        ("UpdateFeatures", {"colors": ["흰색"], "marks": ["얼룩"], "reason": "설명의 털색과 특징을 조건에 넣어요."}),
        ("Finish", {"note": "다시 정렬한 결과가 설명과 맞음"}),
    ])
    run = search(d, MIXED)
    assert run["status"] == "completed" and run["candidates"]
    assert tools_used(run) == ["update_features", "finish"]
    first = client.calls[0][1].content
    assert "사용자 원문" in first and "상위 후보" in first  # 읽을거리는 처음 메시지에 미리 들어 있음
    decision = run["agent_decision"]
    assert decision["source"] == "llm" and decision["final_tool"] == "finish" and decision["reruns"] == 1
    assert run["criteria"]["color"] == "흰색"
    base = search(deps(), MIXED)["trace"].count("rank")
    assert run["trace"].count("rank") == base + 1  # 수정 후 한 번 더 정렬
    assert any(e["step"] == "rerun_result" for e in decision["log"])
    # LLM은 도구 결과(ToolMessage)와 다시 찾은 결과(HumanMessage)를 이어서 받는다.
    last = client.calls[-1]
    assert isinstance(last[-1], HumanMessage) and "다시 찾은 결과" in last[-1].content
    assert any(isinstance(m, ToolMessage) for m in last)
    assert client.bound[1] == {"tool_choice": "required", "parallel_tool_calls": False}


def test_fabricated_feature_rejected_without_rerun():
    d, _ = agent_deps([("UpdateFeatures", {"breed": "말티즈", "reason": "말티즈로 바꿔요."})])
    run = search(d, MIXED)
    log = run["agent_decision"]["log"]
    update = next(e for e in log if e.get("tool") == "update_features")
    assert update["ok"] is False and "원문에 없는 말" in update["rejected"][0]
    assert run["agent_decision"]["reruns"] == 0
    assert run["trace"].count("rank") == search(deps(), MIXED)["trace"].count("rank")  # 다시 찾지 않음


def test_rerun_limit_and_step_limit():
    upd = ("UpdateFeatures", {"colors": ["흰색"], "reason": "털색을 넣어요."})
    run = search(agent_deps([upd, upd, upd])[0], MIXED)
    assert run["agent_decision"]["reruns"] == SA.MAX_RERUNS
    assert run["agent_decision"]["log"][-2]["ok"] is False  # 세 번째 수정은 한도로 거부
    run = search(agent_deps([("RelaxCondition", {"field": "breed", "reason": "풀어요."})] * 10)[0], MIXED)
    assert run["agent_decision"]["source"] == "step_limit" and run["agent_request"] is None
    assert run["candidates"]  # 한도에 걸려도 결과는 보여 준다


def test_widen_radius_rejected_when_radius_not_applied():
    run = search(agent_deps([("WidenRadius", {"reason": "넓혀요."})])[0], MIXED)
    widen = next(e for e in run["agent_decision"]["log"] if e.get("tool") == "widen_radius")
    assert widen["ok"] is False and run["agent_decision"]["reruns"] == 0


def test_photo_request_once_per_thread_and_server_reason():
    d, _ = agent_deps([("RequestPhoto", {"reason": "공고 4411000 과 비슷해요"})])
    first = search(d, MIXED)
    assert first["agent_request"] == {"type": "photo", "reason": SA.rules.DEFAULT_REASON["photo"]}  # 숫자 문장 교체
    d["search_agent"]._client.script = [("RequestPhoto", {"reason": "사진을 올려 주세요."})]
    again = search(d, {"description": "믹스견 흰색 꼬리"}, thread_id=first["thread_id"])
    assert again["agent_request"] is None  # 같은 대화에서 사진은 한 번만
    photo = next(e for e in again["agent_decision"]["log"] if e.get("tool") == "request_photo")
    assert photo["ok"] is False


def test_declined_field_not_requested():
    d, _ = agent_deps([("RequestInfo", {"field": "size", "reason": "크기를 알려 주세요."})])
    run = search(d, MIXED, declined=["size"])
    assert run["agent_request"] is None and run["agent_decision"]["final_tool"] == "finish"


def test_no_llm_or_llm_error_keeps_results():
    run = search(deps(), MIXED)
    assert run["agent_decision"]["source"] == "no_llm" and run["candidates"]
    run = search(agent_deps(error=TimeoutError())[0], MIXED)
    assert run["agent_decision"]["source"] == "llm_error" and run["candidates"]
