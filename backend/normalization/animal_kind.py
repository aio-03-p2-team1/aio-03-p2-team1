"""기타 동물(공공데이터 품종 '기타축종')의 동물 종류 분류.

공공데이터는 기타 동물을 품종 하나('기타축종')로만 주므로, 무슨 동물인지는 특이사항 글이나 사진으로만 알 수 있다.
검색은 글로 먼저 확실한 것을 가리고, 글로 모르는 공고만 사진으로 판단한다. 둘 다 모르면 뺀다(확실히 거른다).
"""

from __future__ import annotations

import re

# 분류 이름 → 특이사항에서 찾을 낱말. '새'처럼 짧아 '새끼'와 겹치는 낱말은 넣지 않는다.
ANIMAL_KINDS: dict[str, tuple[str, ...]] = {
    "새": ("앵무", "사랑새", "잉꼬", "모란", "코뉴어", "카나리아", "문조", "십자매", "비둘기", "참새", "까치",
          "까마귀", "직박구리", "조류", "새장"),
    "토끼": ("토끼",),
    "거북": ("거북", "자라"),
    "고슴도치": ("고슴도치",),
    "햄스터·쥐": ("햄스터", "기니피그", "기니아피그", "친칠라", "다람쥐", "저빌"),
    "페럿": ("페럿", "페렛"),
    "파충류": ("도마뱀", "게코", "이구아나", "뱀", "카멜레온"),
    "소": ("송아지", "한우", "젖소", "황소", "암소"),
    "염소·양": ("염소", "흑염소", "산양"),
    "돼지": ("돼지", "미니피그"),
    "닭·오리": ("닭", "병아리", "오리", "거위", "칠면조", "메추리"),
    "말": ("조랑말", "망아지", "포니"),
}
KIND_NAMES: tuple[str, ...] = tuple(ANIMAL_KINDS)
UNKNOWN = "모름"

_PATTERNS = {kind: re.compile("|".join(map(re.escape, words))) for kind, words in ANIMAL_KINDS.items()}


def kind_from_text(text: str | None) -> str:
    """특이사항 글에서 동물 종류를 찾는다. 한 종류만 분명히 나오면 그 이름, 없거나 여러 종류면 '모름'."""
    compact = "".join((text or "").split())
    found = [kind for kind, pattern in _PATTERNS.items() if pattern.search(compact)]
    return found[0] if len(found) == 1 else UNKNOWN
