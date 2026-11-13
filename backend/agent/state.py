"""검색 그래프 상태 (prompt.md 8장). 필드 설명은 docs/architecture.md 의 상태 표와 같다."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

RunStatus = Literal["running", "awaiting_input", "completed", "partial", "failed"]


class Criteria(TypedDict, total=False):
    species: str  # dog | cat | etc | all
    region: str  # 시도 이름 또는 'all'
    region_code: str | None
    start_date: str  # YYYY-MM-DD
    end_date: str
    pet_name: str
    breed: str
    color: str
    sex: str  # M | F
    age: str
    size: str
    description: str
    lost_place: str
    lost_date: str


class SearchState(TypedDict, total=False):
    # 식별자
    run_id: str
    owner: str
    thread_id: str
    profile_id: str
    # 요청
    request: dict[str, Any]
    criteria: Criteria
    missing: list[str]
    questions: list[dict[str, str]]
    input_errors: list[dict[str, str]]
    # 기억·컨텍스트
    memory_used: dict[str, Any]
    llm_features: dict[str, Any]
    context_summary: dict[str, Any]
    # 계획·실행
    plan: list[dict[str, Any]]
    tool_calls: Annotated[list[dict[str, Any]], operator.add]
    pages_fetched: int
    total_count: int
    raw_items: list[dict[str, Any]]
    data_source: str
    fetched_at: str
    retry_count: int  # 통신 실패 재시도 횟수(판단 오류 수정과 구분)
    # 후보
    candidates: list[dict[str, Any]]
    # 검증·성찰
    issues: list[dict[str, Any]]
    reflection_enabled: bool
    reflection_count: int  # 판단 오류 수정 재실행 횟수
    reflections: Annotated[list[dict[str, Any]], operator.add]
    pending_fix: dict[str, Any] | None
    # 종료
    status: RunStatus
    partial: bool
    scope: dict[str, Any]
    error: dict[str, Any] | None
    end_reason: str
    trace: Annotated[list[str], operator.add]
