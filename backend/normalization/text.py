"""공백·대소문자 차이를 제거하는 검색용 텍스트 정규화."""


def normalize(value: str | None) -> str:
    return "".join(str(value or "").split()).casefold()
