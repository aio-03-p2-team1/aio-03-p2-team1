"""후보 필터·특징 점수·RRF 순위 결합.

- 지역·기간·종류 필터를 먼저 적용한다(이미 API 인자로 걸었더라도 응답을 다시 확인).
- 선택 정보는 가중치로 점수화한다. 누락 필드는 '미확인'으로, 불일치와 구분한다.
- 점수는 동일 동물일 확률이 아니다.

가중치: 품종 3, 털색 3(겹치는 색 하나 이상), 성별 2, 특징 키워드 1개당 1(최대 3)
동점: 점수 내림차순 → 실종일과 발견일이 가까운 순 → 공고 식별자 오름차순
실제 검색은 이 규칙 순위와 임베딩 코사인 순위를 RRF(k=60)로 결합한다.
"""

from __future__ import annotations

import re
import math
from datetime import date
from typing import Any

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

COLOR_SYNONYMS = {
    "갈색": "갈색", "브라운": "갈색", "밤색": "갈색", "초코": "갈색",
    "흰색": "흰색", "하얀": "흰색", "백색": "흰색", "화이트": "흰색", "흰": "흰색",
    "검은": "검정", "검정": "검정", "흑색": "검정", "블랙": "검정", "까만": "검정",
    "회색": "회색", "그레이": "회색", "잿빛": "회색",
    "크림": "크림", "베이지": "크림", "아이보리": "크림",
    "노란": "노랑", "노랑": "노랑", "황색": "노랑", "골드": "노랑",
    "주황": "주황", "오렌지": "주황", "치즈": "주황",
    "삼색": "삼색", "고등어": "고등어", "턱시도": "검정",
}
STOPWORDS = {"있음", "있어요", "있습니다", "입니다", "그리고", "약간", "조금", "정도", "같은", "착용"}


def color_tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    found = set()
    for word, canonical in COLOR_SYNONYMS.items():
        if word in text:
            found.add(canonical)
    return found


def keywords(text: str | None) -> list[str]:
    if not text:
        return []
    words = re.findall(r"[가-힣A-Za-z]{2,}", text)
    out = []
    for w in words:
        if w in STOPWORDS or w in COLOR_SYNONYMS:
            continue
        if w not in out:
            out.append(w)
    return out[:12]


def in_scope(item: dict[str, Any], criteria: dict[str, Any]) -> list[str]:
    """필수 조건 위반 사유 목록(없으면 범위 안)."""
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

    breed = criteria.get("breed") or features.get("breed")
    if breed:
        if not item.get("breed"):
            unknown.append("품종")
        elif breed.replace(" ", "") in item["breed"].replace(" ", "") or item["breed"].replace(" ", "") in breed.replace(" ", ""):
            points += WEIGHTS["breed"]
            matched.append(f"품종: {item['breed']}")
        else:
            mismatched.append(f"품종: {item['breed']}")

    wanted_colors = color_tokens(criteria.get("color")) | color_tokens(criteria.get("description")) | set(features.get("colors") or [])
    if wanted_colors:
        have = color_tokens(item.get("color")) | color_tokens(item.get("special_mark"))
        if not item.get("color") and not item.get("special_mark"):
            unknown.append("털색")
        elif wanted_colors & have:
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
