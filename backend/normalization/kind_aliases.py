"""Curated breed aliases shared by runtime matching and reference-data sync."""

ALIASES = {
    "래브라도리트리버": ["래브라도 리트리버", "라브라도 리트리버"],
    "저먼셰퍼드": ["저먼 셰퍼드", "독일 셰퍼드"],
    "코리안숏헤어": ["코리안 숏헤어", "한국 고양이", "코숏"],
    "믹스견": ["믹스", "혼종견"],
    "토이푸들": ["푸들"],
}


def normalize_kind_name(value: str) -> str:
    """Match the whitespace-insensitive comparison used by the kind catalog."""
    return "".join(str(value or "").split()).casefold()


def is_curated_alias(kind_name: str, alias: str) -> bool:
    """Whether alias is curated for this official kind name."""
    aliases = ALIASES.get(normalize_kind_name(kind_name), ())
    query = normalize_kind_name(alias)
    return bool(query) and any(normalize_kind_name(value) == query for value in aliases)
