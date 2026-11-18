"""Map observed Korean color and coat-pattern expressions to stable IDs."""

from __future__ import annotations

import re
import unicodedata


def _aliases(token: str, *words: str) -> dict[str, frozenset[str]]:
    return {word: frozenset({token}) for word in words}


COLOR_ALIASES: dict[str, frozenset[str]] = {}
for _token, _words in {
    "BLACK": (
        "black", "검", "검정", "검정색", "검은", "검은색", "흑", "흑색", "블랙", "불랙", "까만", "까만색", "깜장",
    ),
    "WHITE": (
        "white", "흰", "흰색", "하양", "하얀", "하얀색", "백", "백색", "화이트", "희", "횐", "벡", "초크색",
    ),
    "BROWN": (
        "brown", "갈", "갈색", "브라운", "밤색", "초코", "초코색", "초콜릿색", "쵸콜릿색",
        "고동색", "흑갈색", "흑갈", "연갈", "연갈색", "진갈", "금갈색", "갈색조합",
    ),
    "TAN": (
        "tan", "황갈", "황갈색", "엷은황갈색", "옅은황갈색", "엷은 황갈색", "옅은 황갈색", "탄", "누렁",
    ),
    "YELLOW": (
        "yellow", "노", "노랑", "노란", "노란색", "노랑색", "황", "황색", "레몬색",
        "옅은황색", "옅은 황색", "연황", "미황",
    ),
    "ORANGE": ("orange", "주", "주황", "주황색", "오렌지", "치즈", "치즈색", "유자"),
    "GOLD": ("gold", "금색", "골드", "골든", "golden"),
    "GRAY": (
        "gray", "grey", "회", "회색", "재색", "잿빛", "쥐색", "그레이", "은색", "실버", "silver",
    ),
    "CREAM": ("cream", "크림", "크림색", "베이지", "아이보리", "미색", "밀색", "보리색"),
    "GREEN": ("green", "녹", "녹색", "암록색", "초", "초록", "초록색", "연두", "연두색", "그린"),
    "BLUE": (
        "blue", "파", "파랑", "파란색", "청", "청색", "첳색", "블루", "하늘색", "바이블루", "파인애플색",
    ),
    "TEAL": ("teal", "청록", "청록색", "청녹", "청녹색"),
    "RED": ("red", "빨", "빨강", "빨간", "빨간색", "적", "적색", "홍", "홍색"),
    "PINK": ("pink", "분홍", "분홍색", "핑크", "핑크색"),
    "PURPLE": ("purple", "보라", "보라색", "자주", "자주색", "라일락", "lilac"),
    "APRICOT": ("apricot", "살구색", "애프리콧"),
    "MUSTARD": ("mustard", "겨자색"),
    "OCHRE": ("ochre", "황토색"),
    "SKIN_TONE": ("살색", "살"),
    "BUFF": ("buff", "인절미"),
    "BRONZE": ("bronze", "브론즈", "브론즈계열"),
    "MULTICOLORED": ("multicolored", "혼합색", "여러가지색", "알록달록"),
}.items():
    COLOR_ALIASES.update(_aliases(_token, *_words))

PATTERN_ALIASES: dict[str, frozenset[str]] = {}
for _token, _words in {
    "TABBY": (
        "tabby", "고등", "고등어", "고등어색", "고등어무늬", "고등어태비", "고등테비", "태비", "테비",
    ),
    "STRIPED": ("striped", "줄", "줄무늬", "검줄"),
    "TUXEDO": ("tuxedo", "턱시도", "컥시도"),
    "SPOTTED": ("spotted", "얼룩", "반점", "호피", "호피무늬", "레오파드", "leopard"),
    "BRINDLE": ("brindle", "브린들", "호반색", "호랑이무늬", "호구"),
    "COW_PATTERN": ("젖소", "바둑이"),
    "CALICO": ("calico", "카오스"),
    "TRICOLOR": ("tricolor", "삼색", "세가지색"),
    "FOUR_COLOR": ("사색",),
    "TORTOISESHELL": ("tortoiseshell", "토터셸"),
    "MERLE": ("merle", "블루멀"),
    "SABLE": ("sable", "세이블"),
    "SALT_AND_PEPPER": ("saltandpepper", "솔트앤페퍼"),
    "SHELL_PATTERN": ("등갑무늬",),
    "MOTTLED": ("미로형무늬",),
    "MASK_MARKING": ("마스카라",),
    "SEAL_BICOLOR": ("씰바이",),
}.items():
    PATTERN_ALIASES.update(_aliases(_token, *_words))

# A few source spellings carry more than one feature in one unbroken word.
_COMPOUND_ALIASES = {
    "블루멀": {"colors": frozenset({"BLUE"}), "patterns": frozenset({"MERLE"})},
    "치즈태비": {"colors": frozenset({"ORANGE"}), "patterns": frozenset({"TABBY"})},
    "흰노색": {"colors": frozenset({"WHITE", "YELLOW"})},
    "검힌": {"colors": frozenset({"BLACK", "WHITE"})},
    "갈검색": {"colors": frozenset({"BROWN", "BLACK"})},
    "흰검색": {"colors": frozenset({"WHITE", "BLACK"})},
    "회검색": {"colors": frozenset({"GRAY", "BLACK"})},
    "황검색": {"colors": frozenset({"YELLOW", "BLACK"})},
}

_LEXEMES: dict[str, dict[str, frozenset[str]]] = {}
for _word, _token in COLOR_ALIASES.items():
    _LEXEMES[_word] = {"colors": _token}
for _word, _token in PATTERN_ALIASES.items():
    _LEXEMES.setdefault(_word, {})["patterns"] = _token
_LEXEMES.update(_COMPOUND_ALIASES)

# These values carry no usable color or pattern evidence, or are animal/breed
# names and other non-color labels present in the source export.
EXCLUDED_COLOR_VALUES: dict[str, str] = {
    "기타(믹스)": "색상 미특정",
    "기타()": "빈 괄호",
    "기타(기타)": "기타 분류만 표기",
    "기타(털색안보임)": "털색 판독 불가",
    "기타(푸들믹스)": "품종 표기",
    "기타(비숑믹스)": "품종 표기",
    "기타(한국고양이)": "종/품종 표기",
    "기타(코숏)": "품종 표기",
    "기타(레그돌)": "품종 표기",
    "기타(스노우벵갈)": "품종 표기",
    "기타(모란앵무)": "종 표기",
    "기타(그린칙)": "종 표기",
    "기타(공작새)": "종 표기",
    "기타(캐비)": "종/품종 불명",
    "기타(척왈라)": "종/품종 불명",
    "기타(조미정)": "색상 표현이 아닌 입력값",
    "기타(스탠다드)": "색상 미특정",
    "기타(Amelanisti)": "색상보다 파충류 모프 표기",
    "기타(회피무늬)": "원문 의미 불명확",
    "기타(.)": "색상 정보 없음",
    "기타(에프리)": "원문 의미 불명확",
    "기타(옅은)": "색상 이름이 완성되지 않은 표현",
    "기타(노멀)": "색상 표현이 아닌 일반 표기",
    "기타(백,검색)": "색상 표현인지 불명확한 오기",
}

_SEPARATORS = re.compile(r"[\s&＋+/／,，·ㆍ|*\[\]{}:：;；.。]+")
_SORTED_LEXEMES = tuple(sorted(_LEXEMES, key=lambda word: (-len(word), word)))


def _complete_segmentation(chunk: str) -> list[str] | None:
    """Segment a fully known concatenated shorthand (e.g. 갈흑백)."""
    best: list[list[str] | None] = [None] * (len(chunk) + 1)
    best[len(chunk)] = []
    for start in range(len(chunk) - 1, -1, -1):
        options = []
        for word in _SORTED_LEXEMES:
            end = start + len(word)
            if chunk.startswith(word, start) and best[end] is not None:
                options.append([word, *best[end]])
        if options:
            best[start] = min(options, key=lambda words: (len(words), tuple(-len(w) for w in words)))
    return best[0]


def _strip_other_wrappers(text: str) -> str:
    """Remove ``기타(...)`` labels with slicing, keeping their inner text."""
    prefix = "기타("
    while True:
        start = text.find(prefix)
        if start < 0:
            return text
        close = text.find(")", start + len(prefix))
        if close < 0:
            return text
        text = text[:start] + text[start + len(prefix):close] + text[close + 1:]


def tokenize_color_words(text: str | None) -> dict[str, set[str]]:
    """Return standard English color and pattern tokens found in text."""
    result = {"colors": set(), "patterns": set()}
    if not text:
        return result

    original = unicodedata.normalize("NFKC", text).strip()
    if original in EXCLUDED_COLOR_VALUES:
        return result
    normalized = _strip_other_wrappers(original.lower())
    chunks = _SEPARATORS.sub(" ", normalized).split()

    for chunk in chunks:
        segmented = _complete_segmentation(chunk)
        if segmented is not None:
            for word in segmented:
                for category, tokens in _LEXEMES[word].items():
                    result[category].update(tokens)
            continue

        # Longest known expressions still extract from descriptive suffixes
        # such as 조합, 무늬, and 색. One-character aliases require a complete
        # segmentation above, preventing matches inside ordinary words.
        index = 0
        while index < len(chunk):
            word = next(
                (
                    candidate
                    for candidate in _SORTED_LEXEMES
                    if len(candidate) > 1 and chunk.startswith(candidate, index)
                ),
                None,
            )
            if word is None:
                index += 1
                continue
            for category, tokens in _LEXEMES[word].items():
                result[category].update(tokens)
            index += len(word)
    return result
