from backend.agent.color_tokenizer import tokenize_color_words
from backend.agent.ranking import score


def test_splits_concatenated_color_words_without_converting_them():
    tokens = tokenize_color_words("검은색흰색황토색조합")

    assert tokens == {"colors": {"검은색", "흰색", "황토색"}, "patterns": set()}


def test_keeps_pattern_words_separate_from_colors():
    tokens = tokenize_color_words("흰색/검은색 얼룩무늬, 기타(턱시도)")

    assert tokens == {
        "colors": {"흰색", "검은색"},
        "patterns": {"얼룩", "턱시도"},
    }


def test_recognizes_separator_delimited_abbreviation_without_substring_false_positive():
    assert tokenize_color_words("기타(검/흰)")["colors"] == {"검", "흰"}
    assert tokenize_color_words("기타(갈/검/흰)")["colors"] == {"갈", "검", "흰"}
    assert tokenize_color_words("검색") == {"colors": set(), "patterns": set()}


def test_aliases_remain_distinct_literal_words():
    user = tokenize_color_words("브라운")
    notice = tokenize_color_words("갈색")

    assert user["colors"] == {"브라운"}
    assert notice["colors"] == {"갈색"}
    assert not (user["colors"] & notice["colors"])


def test_tuxedo_pattern_does_not_match_black_color():
    evidence = score(
        {"color": "검은색", "special_mark": ""},
        {"color": "턱시도"},
    )

    assert "털색" in evidence["mismatched"]
    assert "털색" not in evidence["matched"]


def test_empty_and_unclassified_values_have_no_tokens():
    assert tokenize_color_words(None) == {"colors": set(), "patterns": set()}
    assert tokenize_color_words("기타(믹스)") == {"colors": set(), "patterns": set()}
