import csv
from pathlib import Path

from backend.agent.color_tokenizer import EXCLUDED_COLOR_VALUES
from backend.agent.color_tokenizer import tokenize_color_words
from backend.agent.ranking import score


def test_splits_concatenated_color_words_and_maps_to_standard_ids():
    tokens = tokenize_color_words("검은색흰색황토색조합")

    assert tokens == {"colors": {"BLACK", "WHITE", "OCHRE"}, "patterns": set()}


def test_keeps_pattern_words_separate_from_colors():
    tokens = tokenize_color_words("흰색/검은색 얼룩무늬, 기타(턱시도)")

    assert tokens == {
        "colors": {"WHITE", "BLACK"},
        "patterns": {"SPOTTED", "TUXEDO"},
    }


def test_recognizes_separator_delimited_abbreviation_without_substring_false_positive():
    assert tokenize_color_words("기타(검/흰)")["colors"] == {"BLACK", "WHITE"}
    assert tokenize_color_words("기타(갈/검/흰)")["colors"] == {"BROWN", "BLACK", "WHITE"}
    assert tokenize_color_words("검색") == {"colors": set(), "patterns": set()}


def test_strips_other_wrapper_with_slicing_even_inside_a_sentence():
    expected = {"colors": {"BLACK", "WHITE"}, "patterns": set()}

    assert tokenize_color_words("기타(검/흰)") == expected
    assert tokenize_color_words("털색 표기: 기타(검/흰)") == expected
    assert tokenize_color_words("기타()") == {"colors": set(), "patterns": set()}


def test_aliases_map_to_the_same_english_token():
    user = tokenize_color_words("브라운")
    notice = tokenize_color_words("갈색")

    assert user["colors"] == {"BROWN"}
    assert notice["colors"] == {"BROWN"}


def test_black_aliases_match_ranked_notice_color():
    evidence = score(
        {"color": "검은색", "special_mark": ""},
        {"color": "블랙"},
    )

    assert "털색: 검은색" in evidence["matched"]


def test_tuxedo_pattern_does_not_match_black_color():
    evidence = score(
        {"color": "검은색", "special_mark": ""},
        {"color": "턱시도"},
    )

    assert any(reason.startswith("털색") for reason in evidence["mismatched"])
    assert not any(reason.startswith("털색") for reason in evidence["matched"])


def test_empty_and_unclassified_values_have_no_tokens():
    assert tokenize_color_words(None) == {"colors": set(), "patterns": set()}
    assert tokenize_color_words("기타(믹스)") == {"colors": set(), "patterns": set()}


def test_every_tsv_value_is_tokenized_or_explicitly_excluded():
    path = Path(__file__).parents[1] / "docs" / "data" / "animal-color-combinations.tsv"
    with path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source, delimiter="\t"))

    raw_values = {row["raw_color_cd"] for row in rows}
    assert set(EXCLUDED_COLOR_VALUES) <= raw_values
    assert len(rows) == 1181

    unaccounted = []
    for row in rows:
        raw = row["raw_color_cd"]
        tokens = tokenize_color_words(raw)
        has_tokens = bool(tokens["colors"] or tokens["patterns"])
        if (raw in EXCLUDED_COLOR_VALUES) == has_tokens:
            unaccounted.append(raw)
    assert unaccounted == []
