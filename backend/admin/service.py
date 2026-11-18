"""관리자 화면에서 사용하는 조회 정리·집계 서비스."""

from __future__ import annotations

import re
from collections import Counter
from statistics import mean
from typing import Any

from backend.deps import AppContext
from backend.errors import ApiError

OWNER = re.compile(r"^[0-9a-f]{64}$")
DOC_ID = re.compile(r"^[0-9a-f]{32}$")
SCAN_LIMIT = 500

RUN_LIST_FIELDS = (
    "run_id", "thread_id", "status", "end_reason", "partial", "criteria", "reflection_enabled", "reflection_count",
    "retry_count", "ranking_method", "cache_hit", "data_source", "created_at", "elapsed_ms", "tool_call_count",
    "confidence", "agent_request", "agent_decision", "error", "issues", "radius", "scope",
)
RUN_STAT_FIELDS = (
    "status", "end_reason", "reflection_enabled", "reflection_count", "retry_count", "cache_hit", "elapsed_ms",
    "tool_calls", "confidence", "agent_decision", "agent_request", "issues", "reflections", "ranking_method",
    "error", "created_at",
)

_RUN_LISTS = ("tool_calls", "issues", "reflections", "trace", "questions")
_RUN_DICTS = ("criteria", "confidence", "agent_decision", "agent_request", "radius", "scope")
_RUN_NUMS = ("reflection_count", "retry_count", "tool_call_count", "elapsed_ms")


def _as_list(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def clean_run(run: Any) -> tuple[dict[str, Any], bool]:
    """실행 문서 → (형태를 맞춘 사본, 맞지 않는 값이 있었는지)."""
    if not isinstance(run, dict):
        return {}, True
    out = dict(run)
    odd = False
    for key in _RUN_LISTS:
        if key in out and out[key] is not None:
            cleaned = _as_list(out[key]) if key != "trace" else [v for v in out[key] if isinstance(v, str)] if isinstance(out[key], list) else []
            if key == "tool_calls" and isinstance(out[key], (int, float)) and not isinstance(out[key], bool):
                if out.get("tool_call_count") is None:
                    out["tool_call_count"] = int(out[key])
            odd = odd or not isinstance(out[key], list) or len(cleaned) != len(out[key])
            out[key] = cleaned
    for key in _RUN_DICTS:
        if key in out and out[key] is not None and not isinstance(out[key], dict):
            odd = True
            out[key] = None
    if "error" in out and out["error"] is not None and not isinstance(out["error"], dict):
        odd = True
        out["error"] = {"code": str(out["error"])[:80]}
    for key in _RUN_NUMS:
        value = out.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            odd = True
            out[key] = None
    decision = out.get("agent_decision")
    if decision is not None:
        log = decision.get("log")
        if log is not None and not isinstance(log, list):
            odd = True
        out["agent_decision"] = {**decision, "log": _as_list(log)}
    confidence = out.get("confidence")
    if confidence is not None:
        reasons = confidence.get("reasons")
        out["confidence"] = {
            **confidence,
            "reasons": [reason for reason in reasons if isinstance(reason, str)] if isinstance(reasons, list) else [],
        }
    for key in ("status", "end_reason", "ranking_method", "data_source", "created_at"):
        if out.get(key) is not None and not isinstance(out[key], str):
            odd = True
            out[key] = str(out[key])
    return out, odd


def check_owner(owner: str) -> None:
    if not OWNER.match(owner):
        raise ApiError(404, "not_found", "대상을 찾을 수 없습니다.")


def check_id(doc_id: str) -> None:
    if not DOC_ID.match(doc_id):
        raise ApiError(404, "not_found", "대상을 찾을 수 없습니다.")


async def accounts(ctx: AppContext) -> dict[str, dict[str, Any]]:
    """소유자 키 → {email, name}. 비밀번호 해시는 꺼내지 않는다."""
    rows = await ctx.store.list_kind("identity", SCAN_LIMIT)
    return {row["owner"]: {"email": row["data"].get("email"), "name": row["data"].get("name")} for row in rows}


def who(account_rows: dict[str, dict[str, Any]], owner: str | None) -> dict[str, Any]:
    account = account_rows.get(owner or "") or {}
    return {"owner": owner, "email": account.get("email"), "name": account.get("name")}


def run_row(row: dict[str, Any], account_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run, malformed = clean_run(row["data"])
    decision = run.get("agent_decision") or {}
    confidence = run.get("confidence") or {}
    return {
        **who(account_rows, row["owner"]),
        "id": row["id"],
        "status": run.get("status"),
        "end_reason": run.get("end_reason"),
        "criteria": run.get("criteria"),
        "reflection_enabled": run.get("reflection_enabled"),
        "reflection_count": run.get("reflection_count") or 0,
        "retry_count": run.get("retry_count") or 0,
        "tool_call_count": run.get("tool_call_count") or 0,
        "cache_hit": bool(run.get("cache_hit")),
        "elapsed_ms": run.get("elapsed_ms"),
        "data_source": run.get("data_source"),
        "ranking_method": run.get("ranking_method"),
        "confidence_low": bool(confidence.get("low")),
        "confidence_reasons": confidence.get("reasons") or [],
        "agent_source": decision.get("source"),
        "agent_final_tool": decision.get("final_tool"),
        "agent_steps": decision.get("steps") or 0,
        "agent_reruns": decision.get("reruns") or 0,
        "agent_request": (run.get("agent_request") or {}).get("type"),
        "issues": [issue.get("type") for issue in run.get("issues") or [] if isinstance(issue, dict)],
        "error": (run.get("error") or {}).get("code"),
        "radius_km": (run.get("radius") or {}).get("km"),
        "created_at": run.get("created_at") or row.get("updated_at"),
        "malformed": malformed,
    }


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 2) if values else None


def _group_stats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """성찰 켬/끔 비교에 쓰는 실행 묶음 요약(보고서 지표의 원자료)."""
    count = len(runs)
    done = sum(1 for run in runs if run.get("status") in ("completed", "partial"))
    return {
        "runs": count,
        "completed_rate": _rate(done, count),
        "failed_rate": _rate(sum(1 for run in runs if run.get("status") == "failed"), count),
        "awaiting_input_rate": _rate(sum(1 for run in runs if run.get("status") == "awaiting_input"), count),
        "avg_reflection_count": _avg([run.get("reflection_count") or 0 for run in runs]),
        "avg_retry_count": _avg([run.get("retry_count") or 0 for run in runs]),
        "avg_tool_calls": _avg([len(run.get("tool_calls") or []) or run.get("tool_call_count") or 0 for run in runs]),
    }


def agent_stats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """실행 문서 목록 → 에이전트 정확도 개선용 집계."""
    runs = [clean_run(run)[0] for run in runs]
    total = len(runs)
    executed = [run for run in runs if not run.get("cache_hit")]
    tool_use: Counter = Counter()
    tool_fail: Counter = Counter()
    for run in executed:
        for call in run.get("tool_calls") or []:
            name = call.get("tool") or "?"
            tool_use[name] += 1
            if call.get("outcome") not in ("ok", "hit", "cached", None):
                tool_fail[name] += 1
    agent_runs = [run for run in executed if run.get("agent_decision")]
    agent_tool: Counter = Counter()
    agent_rejected: Counter = Counter()
    rejected_examples: list[dict[str, Any]] = []
    for run in agent_runs:
        for step in (run["agent_decision"].get("log") or []):
            if not step.get("tool"):
                continue
            agent_tool[step["tool"]] += 1
            if step.get("ok") is False:
                agent_rejected[step["tool"]] += 1
                if len(rejected_examples) < 20:
                    rejected_examples.append({"tool": step["tool"], "args": step.get("args"),
                                              "reason": step.get("rejected"), "at": run.get("created_at")})
    low = [run for run in executed if (run.get("confidence") or {}).get("low")]
    with_reflection = [run for run in executed if run.get("reflection_enabled") is not False]
    without_reflection = [run for run in executed if run.get("reflection_enabled") is False]
    return {
        "total_runs": total,
        "executed_runs": len(executed),
        "cache_hit_rate": _rate(total - len(executed), total),
        "status": dict(Counter(run.get("status") or "unknown" for run in runs)),
        "end_reason": dict(Counter(run.get("end_reason") or "-" for run in runs)),
        "errors": dict(Counter((run.get("error") or {}).get("code") for run in runs if run.get("error"))),
        "avg_elapsed_ms": _avg([run["elapsed_ms"] for run in executed if isinstance(run.get("elapsed_ms"), (int, float))]),
        "issues": dict(Counter(issue.get("type") for run in executed for issue in run.get("issues") or [] if isinstance(issue, dict))),
        "reflections": dict(Counter(item.get("type") or item.get("issue") for run in executed for item in run.get("reflections") or []
                                    if isinstance(item, dict))),
        "tool_use": dict(tool_use.most_common()),
        "tool_fail": dict(tool_fail.most_common()),
        "confidence": {
            "low_rate": _rate(len(low), len(executed)),
            "reasons": dict(Counter(reason for run in low for reason in (run["confidence"].get("reasons") or []))),
        },
        "agent": {
            "runs": len(agent_runs),
            "source": dict(Counter(run["agent_decision"].get("source") or "-" for run in agent_runs)),
            "final_tool": dict(Counter(run["agent_decision"].get("final_tool") or "-" for run in agent_runs)),
            "tool_calls": dict(agent_tool.most_common()),
            "rejected": dict(agent_rejected.most_common()),
            "avg_steps": _avg([run["agent_decision"].get("steps") or 0 for run in agent_runs]),
            "avg_reruns": _avg([run["agent_decision"].get("reruns") or 0 for run in agent_runs]),
            "requests": dict(Counter((run.get("agent_request") or {}).get("type") for run in agent_runs if run.get("agent_request"))),
            "rejected_examples": rejected_examples,
        },
        "reflection_compare": {"on": _group_stats(with_reflection), "off": _group_stats(without_reflection)},
    }
