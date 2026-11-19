from backend.agent.ranking import score
from backend.normalization import profile


def test_user_values_are_kept_only_when_the_number_is_in_the_text():
    assert profile.user_age_years("3살", "중성화했고 3살이에요") == 3
    assert profile.user_age_years("6개월", "6개월 된 아기") == 0.5
    assert profile.user_age_years("5살", "3살이에요") is None  # 글에 없는 숫자
    assert profile.user_age_years("2020년생", "2020년생") is None  # 출생 연도는 쓰지 않음
    assert profile.user_weight_kg("4.5kg", "4.5키로쯤") == 4.5
    assert profile.user_weight_kg("4kg", "14kg") is None  # 다른 숫자의 일부
    assert profile.user_weight_kg("800g", "800g 정도") == 0.8
    assert profile.user_neuter("Y", "중성화 했어요") == "Y"
    assert profile.user_neuter("Y", "흰 강아지") == ""


def test_notice_values_from_the_animal_api_format():
    assert profile.notice_age_years("2023(년생)", 2026) == 3
    assert profile.notice_age_years("60일미만(년생)", 2026) == 0
    assert profile.notice_age_years("", 2026) is None
    assert profile.notice_weight_kg("3.2(Kg)") == 3.2
    assert profile.notice_weight_kg("") is None


def item(**kw):
    return {"id": "1", "color": "흰색", "sex": "F", "special_mark": "", "happen_date": "2026-11-10", **kw}


def test_score_adds_points_for_close_neuter_age_weight_without_filtering():
    features = {"neuter": "Y", "age_years": 3, "weight_kg": 4.0}
    close = score(item(neuter="Y", age="2024(년생)", weight="4.5(Kg)"), {}, features)
    far = score(item(neuter="N", age="2015(년생)", weight="12(Kg)"), {}, features)
    unknown = score(item(neuter="U", age="", weight=""), {}, features)
    assert close["score"] == 3 and "중성화 했음" in close["matched"]
    assert far["score"] == 0 and "중성화 다름" in far["mismatched"]
    assert unknown["score"] == 0 and set(unknown["unknown"]) >= {"중성화", "나이", "몸무게"}


def test_rank_drops_kittens_when_the_text_says_an_adult_age():
    from backend.agent.ranking import rank

    items = [item(id="kitten", age="2026(년생)"), item(id="baby", age="60일미만(년생)"),
             item(id="adult", age="2020(년생)"), item(id="unknown", age="")]
    kept = [c["id"] for c in rank(items, {}, {"age_years": 6})]
    assert set(kept) == {"adult", "unknown"}
    # 나이를 적지 않았으면 거르지 않는다.
    assert len(rank(items, {}, {})) == 4
    # 새끼를 찾으면 3살 이상 공고를 뺀다.
    kept = [c["id"] for c in rank([item(id="old", age="2020(년생)"), item(id="young", age="2026(년생)")], {}, {"age_years": 0.5})]
    assert kept == ["young"]
