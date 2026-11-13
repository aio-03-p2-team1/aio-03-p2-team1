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
    data_source: str
    fetched_at: str
    retry_count: int

    candidates: list[dict[str, Any]]

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
