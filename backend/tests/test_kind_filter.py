"""품종 계열·기타 동물 종류 거르기 규칙(0건이 되더라도 엉뚱한 후보는 뺀다)."""

import pytest

from backend.agent.ranking import breed_family, breed_matches
from backend.normalization.animal_kind import UNKNOWN, kind_from_text


@pytest.mark.parametrize("item, breed, expected", [
    ({"breed": "푸들"}, "토이 푸들", True),
    ({"breed": "미니어쳐 푸들"}, "푸들", True),
    ({"breed": "골든 리트리버"}, "푸들", False),
    ({"breed": "믹스견", "special_mark": "푸들 믹스 추정"}, "토이 푸들", True),
    ({"breed": "믹스견", "special_mark": "갈색 단모"}, "푸들", False),
    ({"breed": "기타"}, "푸들", False),
    ({"breed": "믹스견"}, "믹스견", True),
    ({"breed": "도사 믹스견"}, "믹스견", False),
    ({"breed": "도사 믹스견"}, "도사", True),
    ({"breed": "코리안 숏헤어"}, "코리안숏헤어", True),
])
def test_breed_matches_family_and_mix_rules(item, breed, expected):
    assert breed_matches(item, breed) is expected


def test_breed_family_strips_size_prefix_only():
    assert breed_family("토이 푸들") == breed_family("스탠다드 푸들") == "푸들"
    assert breed_family("미니") == "미니"


@pytest.mark.parametrize("text, kind", [
    ("사랑앵무 초록색", "새"),
    ("송아지 생후 2개월", "소"),
    ("새끼 토끼", "토끼"),        # '새끼'를 새로 보지 않는다
    ("쥐색 털", UNKNOWN),          # '쥐색'을 쥐로 보지 않는다
    ("순하며 큰 뿔에 줄이 감겨있음", UNKNOWN),
    ("염소와 닭 함께 발견", UNKNOWN),  # 여러 종류면 모름
    ("", UNKNOWN),
])
def test_kind_from_text(text, kind):
    assert kind_from_text(text) == kind
