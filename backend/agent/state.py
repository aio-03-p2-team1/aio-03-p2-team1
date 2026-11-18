from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

RunStatus = Literal["running", "awaiting_input", "completed", "partial", "failed"]


class Criteria(TypedDict, total=False):
    species: str
    region: str
    region_code: str | None
    start_date: str
    end_date: str
    pet_name: str
    breed_code: str | None
    breed: str
    color: str
    sex: str
    age: str
    size: str
    description: str
    lost_place: str
    lost_date: str
    radius_step: int  # 사용자가 넓히기에 동의한 반경 단계(0~3). 없으면 실종 날짜로 추천 단계 계산


class SearchState(TypedDict, total=False):

    run_id: str
    owner: str
    thread_id: str
    profile_id: str

    request: dict[str, Any]
    criteria: Criteria
    missing: list[str]
    questions: list[dict[str, str]]
    input_errors: list[dict[str, str]]

    memory_used: dict[str, Any]
    llm_features: dict[str, Any]
    photo_features: dict[str, Any] | None  # 서버가 보관한 사진 분석 결과(photo_store). 사진을 받았는지 판단은 이 값으로만
    semantic_scores: dict[str, float] | None
    ranking_method: str
    context_summary: dict[str, Any]

    plan: list[dict[str, Any]]
    tool_calls: Annotated[list[dict[str, Any]], operator.add]
    pages_fetched: int
    total_count: int
    raw_items: list[dict[str, Any]]
    search_query: dict[str, Any]  # 실제 API 조회 인자. 로컬 조건 완화 뒤에도 API 필터 출처를 보존
    radius_items: list[dict[str, Any]] | None  # 반경 안 + 거리 미확인 공고(반경 밖 제외). 임베딩·정렬 대상
    radius: dict[str, Any]  # 반경 단계·km·중심 좌표·포함/제외 건수·미적용 사유
    data_source: str
    fetched_at: str
    retry_count: int

    candidates: list[dict[str, Any]]
    confidence: dict[str, Any] | None  # 결과 확신 신호(low, reasons, signals). validate 가 계산
    agent_history: dict[str, Any]  # 같은 대화에서 에이전트가 이미 요청한 것(반복 요청 방지)
    agent_request: dict[str, Any] | None  # 에이전트가 끝내며 고른 요청(사진·추가 정보). 없으면 None
    agent_decision: dict[str, Any] | None  # 에이전트 판단 기록(출처, 마지막 도구, 걸음·다시 찾기 수, 단계별 로그)
    # 검색 에이전트 루프(agent ⇄ agent_tools) 작업 상태. 응답(run)에는 agent_decision 만 남긴다.
    agent_messages: list[Any]  # LLM 대화(시스템·신호·도구 호출·도구 결과)
    agent_steps: int  # LLM 걸음 수
    agent_reruns: int  # 재정렬·반경 변경·API 재조회 전략 시도 수
    agent_done: bool
    agent_next: str | None  # 도구 실행 후 갈 노드(rank·radius·research·ask). 없으면 다시 agent
    agent_researches: int  # 실제 공고 재조회 시도 수(통신 재시도와 구분)
    agent_search_plan: dict[str, Any] | None  # 서버가 검증한 재조회 계획. 성공 후에만 조건·원본에 반영
    agent_rerun_pending: bool  # 다시 찾은 결과를 다음 agent 걸음에 알려야 함
    agent_source: str  # 사용자 원문(수정 값 검증의 근거). 처음 걸음에 고정
    agent_before: dict[str, Any]  # 다시 찾기 전 결과 요약(이전 대비 비교용)
    agent_log: list[dict[str, Any]]  # 단계별 기록: 읽기·수정·거부·다시 찾은 결과

    issues: list[dict[str, Any]]
    reflection_enabled: bool
    reflection_count: int
    reflections: Annotated[list[dict[str, Any]], operator.add]
    pending_fix: dict[str, Any] | None

    status: RunStatus
    partial: bool
    scope: dict[str, Any]
    error: dict[str, Any] | None
    end_reason: str
    trace: Annotated[list[str], operator.add]
