"""Extract literal color and pattern words from user and notice text."""

from __future__ import annotations

import re
import unicodedata

# These are lexical forms, not synonym-to-canonical-color mappings. Keep each
# observed word as its own token so callers can decide matching policy.
COLOR_WORDS = (
    "쵸콜릿색", "아이보리", "레몬색", "황토색", "황갈색", "노란색", "검은색", "검정색",
    "초콜릿색", "베이지", "크림색", "미색", "하얀색", "흰색", "화이트", "백색",
    "검정", "검은", "흑색", "블랙", "갈색", "브라운", "밤색", "초코", "회색",
    "그레이", "잿빛", "은색", "실버", "크림", "노랑", "황색", "금색", "골드",
    "주황", "오렌지", "치즈색", "치즈", "흰", "하양",
)

PATTERN_WORDS = (
    "줄무늬", "고등어", "턱시도", "얼룩", "삼색", "태비", "호반", "젖소", "카오스",
)

# One-character abbreviations are recognized only as complete separator
# delimited chunks, so they cannot match inside unrelated words.
_SHORT_COLOR_WORDS = {"검", "갈"}
_WORDS = tuple(sorted(set(COLOR_WORDS + PATTERN_WORDS), key=lambda word: (-len(word), word)))
_SEPARATORS = re.compile(r"[\s&＋+/／,，·ㆍ|()（）\[\]{}:：;；]+")


def tokenize_color_words(text: str | None) -> dict[str, set[str]]:
    """Return literal color/pattern terms found in text, without alias mapping.

    Longest terms are consumed first, which handles concatenated API values
    such as ``검은색흰색황토색조합`` while preserving each spelling.
    """
    result = {"colors": set(), "patterns": set()}
    if not text:
        return result

    normalized = unicodedata.normalize("NFKC", text).lower()
    # Parentheses are separators, so ``기타(삼색)`` exposes ``삼색`` directly.
    normalized = _SEPARATORS.sub(" ", normalized)
    category = {word: "colors" for word in COLOR_WORDS}
    category.update({word: "patterns" for word in PATTERN_WORDS})

    for chunk in normalized.split():
        if chunk in _SHORT_COLOR_WORDS:
            result["colors"].add(chunk)
            continue
        index = 0
        while index < len(chunk):
            matched = next((word for word in _WORDS if chunk.startswith(word, index)), None)
            if matched is None:
                index += 1
                continue
            result[category[matched]].add(matched)
            index += len(matched)
    return result
