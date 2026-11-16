from __future__ import annotations

import re
import math
from datetime import date
from typing import Any

from backend.agent.color_tokenizer import tokenize_color_words

WEIGHTS = {"breed": 3, "color": 3, "sex": 2, "keyword": 1}
MAX_KEYWORD_POINTS = 3
TOP_K = 300
RRF_K = 60


def feature_text(item: dict) -> str:
    return " · ".join(f"{key}: {item[key]}" for key in
                     ("species", "breed", "color", "sex", "age", "size", "weight", "description", "special_mark")
                     if item.get(key))[:2000] or "동물 특징 미확인"


def cosine(left, right):
    if len(left) != len(right) or not left:
        raise ValueError("벡터 차원이 다릅니다")
    left_norm, right_norm = math.hypot(*left), math.hypot(*right)
    if not left_norm or not right_norm or not math.isfinite(left_norm + right_norm):
        raise ValueError("유효하지 않은 벡터")
    return sum((a / left_norm) * (b / right_norm) for a, b in zip(left, right))


def fuse_rrf(lexical, semantic_scores):
    semantic = sorted(lexical, key=lambda item: (-semantic_scores[item["id"]], item["id"]))
    lexical_positions, semantic_positions = {}, {}
    for pos, item in enumerate(lexical, 1):
        lexical_positions.setdefault(item["id"], pos)
    for pos, item in enumerate(semantic, 1):
        semantic_positions.setdefault(item["id"], pos)
    result = []
    for item in lexical:
        identifier = item["id"]
        rrf = 1 / (RRF_K + lexical_positions[identifier]) + 1 / (RRF_K + semantic_positions[identifier])
        result.append({**item, "lexical_score": item["score"], "score": rrf,
                       "semantic_score": semantic_scores[identifier],
                       "rrf_ranks": {"lexical": lexical_positions[identifier], "semantic": semantic_positions[identifier]}})
    result.sort(key=lambda item: (-item["score"], lexical_positions[item["id"]], item["id"]))
    return [{**item, "rank": index} for index, item in enumerate(result, 1)]

STOPWORDS = {"있음", "있어요", "있습니다", "입니다", "그리고", "약간", "조금", "정도", "같은", "착용"}


def color_tokens(text: str | None) -> set[str]:
    tokens = tokenize_color_words(text)
    return tokens["colors"] | tokens["patterns"]


def keywords(text: str | None) -> list[str]:
    if not text:
        return []
    words = re.findall(r"[가-힣A-Za-z]{2,}", text)
    out = []
    for w in words:
        if w in STOPWORDS or color_tokens(w):
            continue
        if w not in out:
            out.append(w)
    return out[:12]


def in_scope(item: dict[str, Any], criteria: dict[str, Any]) -> list[str]:

    reasons = []
    species = criteria.get("species")
    if species and species != "all" and item.get("species") and item["species"] != species:
        reasons.append("species")
    happen = item.get("happen_date")
    if happen and criteria.get("start_date") and criteria.get("end_date"):
        if not (criteria["start_date"] <= happen <= criteria["end_date"]):
            reasons.append("period")
    return reasons


def score(item: dict[str, Any], criteria: dict[str, Any], features: dict[str, Any] | None = None) -> dict[str, Any]:
    features = features or {}
    matched, mismatched, unknown = [], [], []
    points = 0

    breed = criteria.get("breed")
    if breed:
        if not item.get("breed"):
            unknown.append("품종")
        elif breed.replace(" ", "") in item["breed"].replace(" ", "") or item["breed"].replace(" ", "") in breed.replace(" ", ""):
            points += WEIGHTS["breed"]
            matched.append(f"품종: {item['breed']}")
        else:
            mismatched.append(f"품종: {item['breed']}")

    wanted = tokenize_color_words(criteria.get("color"))
    described = tokenize_color_words(criteria.get("description"))
    wanted_colors = wanted["colors"] | described["colors"]
    wanted_patterns = wanted["patterns"] | described["patterns"]
    wanted_color_words = wanted_colors | wanted_patterns
    if wanted_color_words:
        have_color = tokenize_color_words(item.get("color"))
        have_mark = tokenize_color_words(item.get("special_mark"))
        have_colors = have_color["colors"] | have_mark["colors"]
        have_patterns = have_color["patterns"] | have_mark["patterns"]
        have = have_colors | have_patterns
        if not item.get("color") and not item.get("special_mark"):
            unknown.append("털색")
        elif wanted_color_words & have:
            points += WEIGHTS["color"]
            matched.append(f"털색: {item.get('color') or '특징에 표기'}")
        else:
            mismatched.append(f"털색: {item.get('color') or '미표기'}")

    sex = criteria.get("sex") or features.get("sex")
    if sex:
        if item.get("sex") not in ("M", "F"):
            unknown.append("성별")
        elif item["sex"] == sex:
            points += WEIGHTS["sex"]
            matched.append("성별 일치")
        else:
            mismatched.append("성별 다름")

    wanted_keywords = keywords(criteria.get("description")) + [k for k in (features.get("marks") or []) if isinstance(k, str)]
    if wanted_keywords:
        mark = item.get("special_mark") or ""
        hits = [k for k in dict.fromkeys(wanted_keywords) if k and k in mark]
        if not mark:
            unknown.append("특징")
        elif hits:
            points += min(len(hits), MAX_KEYWORD_POINTS) * WEIGHTS["keyword"]
            matched.append("특징: " + ", ".join(hits[:MAX_KEYWORD_POINTS]))

    return {"score": points, "matched": matched, "mismatched": mismatched, "unknown": unknown}


def _date_gap(item: dict[str, Any], lost_date: str | None) -> int:
    if not lost_date or not item.get("happen_date"):
        return 10**6
    try:
        return abs((date.fromisoformat(item["happen_date"]) - date.fromisoformat(lost_date)).days)
    except ValueError:
        return 10**6


def rank(items: list[dict[str, Any]], criteria: dict[str, Any], features: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    lost_date = criteria.get("lost_date") or criteria.get("start_date")
    out = []
    for item in items:
        if in_scope(item, criteria):
            continue
        evidence = score(item, criteria, features)
        out.append({**item, "evidence": evidence, "score": evidence["score"]})
    out.sort(key=lambda c: (-c["score"], _date_gap(c, lost_date), c["id"]))
    for i, c in enumerate(out, start=1):
        c["rank"] = i
    return out


# ── 결과 확신 신호 (에이전트 판단용) ──────────────────────────────
# RRF 점수는 순위로만 계산(1/(k+순위))해서 결과가 엉망이어도 1등 점수가 비슷하다. "얼마나 닮았나"를 말해 주지 않는다.
# 그래서 확신은 절대적인 신호(벡터 유사도 값, 특징 일치 근거, 입력 특징의 양)로 판단한다.
# 기준값은 실제 검색 몇 건을 보고 정한 것이 아니라 임시값이다(CONFIDENCE_VERSION 으로 기록, 측정 후 조정).
CONFIDENCE_VERSION = "conf-v1(임시 기준)"
WEAK_SIMILARITY = 0.45  # 1등 후보 벡터 유사도가 이보다 낮으면 애매
FLAT_GAP = 0.01  # 1·2등 유사도 차이가 이보다 작으면 두드러진 후보가 없음
MIXED_WORDS = ("믹스", "잡종", "혼종", "mix")
PHOTO_PREFIX = "사진에서 확인한 특징"  # 화면이 사진 분석 결과를 설명 글 앞에 붙일 때 쓰는 말


def input_signals(criteria: dict[str, Any], features: dict[str, Any] | None = None) -> dict[str, Any]:
    """사용자가 준 특징이 얼마나 구체적인지. 모두 입력·추출 결과에서 계산한다(추측 없음)."""
    features = features or {}
    text = " ".join(str(criteria.get(k) or "") for k in ("breed", "color", "description"))
    colors = tokenize_color_words(f"{criteria.get('color') or ''} {criteria.get('description') or ''}")
    marks = [k for k in keywords(criteria.get("description")) if k not in MIXED_WORDS]
    return {
        "breed_given": bool(criteria.get("breed")),
        "breed_mixed": any(w in text.lower() for w in MIXED_WORDS),
        "color_given": bool(colors["colors"] or colors["patterns"] or features.get("colors")),
        "sex_given": bool(criteria.get("sex") or features.get("sex")),
        "size_given": bool(criteria.get("size")),
        "marks_given": bool(marks or features.get("marks")),
        "photo_given": PHOTO_PREFIX in str(criteria.get("description") or ""),
    }


def confidence_signals(candidates: list[dict[str, Any]], criteria: dict[str, Any],
                       features: dict[str, Any] | None = None) -> dict[str, Any]:
    """정렬된 후보에서 확신 신호를 계산한다. low=True 면 에이전트가 추가 정보·사진 요청을 판단한다."""
    given = input_signals(criteria, features)
    feature_count = sum(given[k] for k in ("breed_given", "color_given", "sex_given", "size_given", "marks_given"))
    sims = sorted((c["semantic_score"] for c in candidates[:20] if isinstance(c.get("semantic_score"), (int, float))),
                  reverse=True)
    top = candidates[0] if candidates else {}
    evidence = top.get("evidence") or {}
    signals = {
        **given,
        "feature_count": feature_count,
        "candidates": len(candidates),
        "top_similarity": round(sims[0], 3) if sims else None,
        "similarity_gap": round(sims[0] - sims[1], 3) if len(sims) > 1 else None,
        "top_matched": len(evidence.get("matched") or []),
        "top_unknown": len(evidence.get("unknown") or []),
    }
    reasons = []
    if candidates:
        if feature_count <= 1:
            reasons.append("few_features")  # 특징이 거의 없음
        if given["breed_mixed"] and not given["photo_given"]:
            reasons.append("mixed_breed")  # 믹스견: 품종·털색만으로 구분이 어려움
        if signals["top_similarity"] is not None and signals["top_similarity"] < WEAK_SIMILARITY:
            reasons.append("weak_similarity")
        if signals["similarity_gap"] is not None and len(sims) >= 3 and signals["similarity_gap"] < FLAT_GAP:
            reasons.append("flat_top")
        if feature_count and signals["top_matched"] == 0:
            reasons.append("no_feature_match")
    return {"low": bool(reasons), "reasons": reasons, "signals": signals, "version": CONFIDENCE_VERSION}
