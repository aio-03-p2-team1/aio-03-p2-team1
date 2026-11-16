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
    semantic_scores: dict[str, float] | None
    ranking_method: str
    context_summary: dict[str, Any]

    plan: list[dict[str, Any]]
    tool_calls: Annotated[list[dict[str, Any]], operator.add]
    pages_fetched: int
    total_count: int
    raw_items: list[dict[str, Any]]
    radius_items: list[dict[str, Any]] | None  # 반경 안 + 거리 미확인 공고(반경 밖 제외). 임베딩·정렬 대상
    radius: dict[str, Any]  # 반경 단계·km·중심 좌표·포함/제외 건수·미적용 사유
    data_source: str
    fetched_at: str
    retry_count: int

    candidates: list[dict[str, Any]]
    confidence: dict[str, Any] | None  # 결과 확신 신호(low, reasons, signals). validate 가 계산
    agent_history: list[dict[str, Any]]  # 같은 대화에서 에이전트가 이미 요청한 것(반복 요청 방지)
    agent_request: dict[str, Any] | None  # assess 가 고른 요청(사진·추가 정보). 없으면 None
    agent_decision: dict[str, Any] | None  # assess 판단 기록(고른 도구, 이유, 허용 행동, 프롬프트 버전)

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
