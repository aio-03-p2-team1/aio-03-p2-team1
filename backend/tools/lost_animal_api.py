"""분실동물 조회 서비스 API 도구 (실종 정보 게시판용).

공식 문서: https://www.data.go.kr/data/15141910/openapi.do
주소: https://apis.data.go.kr/1543061/lossInfoService

| 기능         | 경로               | 필수 요청 변수                    |
| ------------ | ------------------ | --------------------------------- |
| 분실동물 조회 | lossInfo           | serviceKey, bgnde, ended(YYYYMMDD) |
| 시도 조회     | lossInfoSido       | serviceKey                        |
| 시군구 조회   | lossInfoSigungu    | serviceKey, upr_cd                |
| 품종 조회     | lossInfoKind       | serviceKey, up_kind_cd            |

지켜야 할 것
- 응답 항목(item)의 필드 이름은 공식 페이지에 없다. 실제 응답으로 확인하기 전까지는
  필드를 해석하지 않고 원본 그대로 돌려준다. 화면용 변환(신고자 개인정보 제거 포함)은
  필드를 확인한 뒤 따로 만든다. → 이 단계에서는 이 도구를 화면·API 응답에 연결하지 않는다.
- 인증 오류·통신 실패를 빈 결과로 바꾸지 않는다(LostAnimalApiError). 빈 결과(0건)와 실패를 구분한다.
- 키 값을 로그·예외 메시지에 넣지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import unquote

import httpx

# 축종 코드(공식 문서): 개 417000, 고양이 422400, 기타 429900
UPKIND = {"dog": "417000", "cat": "422400", "etc": "429900"}
MAX_ROWS = 1000  # 공식 문서상 numOfRows 최대값


class LostAnimalApiError(RuntimeError):
    """분실동물 API 호출 실패. code 는 화면 안내·기록에 쓰는 고정 문자열이다."""

    def __init__(self, code: str, status: int | None = None, result_code: str | None = None):
        super().__init__(code)
        self.code = code  # lost_auth | lost_rate_limit | lost_timeout | lost_network | lost_upstream | lost_response
        self.status = status  # HTTP 상태 코드
        self.result_code = result_code  # 공공데이터포털 resultCode (예: 30 = 등록되지 않은 키)


@dataclass
class LostPage:
    """분실동물 조회 한 페이지. items 는 API 원본 항목(아직 해석하지 않음)."""

    items: list[dict[str, Any]]
    total_count: int
    page: int
    rows: int


def _ymd(value: date) -> str:
    """date → API 날짜 형식(YYYYMMDD)."""
    return value.strftime("%Y%m%d")


def _items_of(body: dict[str, Any]) -> list[dict[str, Any]]:
    """body.items.item 을 항상 list 로 꺼낸다. (1건이면 dict, 0건이면 빈 문자열로 오는 경우가 있다)"""
    items = body.get("items")
    if not isinstance(items, dict):
        return []
    item = items.get("item")
    if item is None:
        return []
    return item if isinstance(item, list) else [item]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class LostAnimalApi:
    """분실동물 조회 서비스 클라이언트. 구조동물 클라이언트(animal_api.AnimalApi)와 같은 오류 규칙을 따른다."""

    def __init__(self, base_url: str, service_key: str, timeout: float = 20, transport=None):
        # 포털의 Encoding 키(%2B 등 포함)를 넣어도 동작하도록 한 번 풀어 둔다. httpx 가 요청 시 다시 인코딩한다.
        key = service_key.strip()
        if "%" in key:
            key = unquote(key)
        self._key = key
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """공통 호출. 정상이면 response.body 를, 아니면 LostAnimalApiError 를 낸다."""
        query = {"serviceKey": self._key, "_type": "json", **{k: v for k, v in params.items() if v is not None}}
        try:
            res = await self._client.get("/" + path, params=query)
        except httpx.TimeoutException as exc:
            raise LostAnimalApiError("lost_timeout") from exc
        except httpx.HTTPError as exc:
            raise LostAnimalApiError("lost_network") from exc

        # 키 오류·호출 한도 초과는 JSON 대신 XML/글자로 오는 경우가 있어 본문 문자열로도 확인한다.
        text = res.text
        if res.status_code in (401, 403) or "SERVICE_KEY_IS_NOT_REGISTERED" in text:
            raise LostAnimalApiError("lost_auth", res.status_code, "30" if "NOT_REGISTERED" in text else None)
        if res.status_code == 429 or "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in text:
            raise LostAnimalApiError("lost_rate_limit", res.status_code, "22")
        if res.status_code >= 500:
            raise LostAnimalApiError("lost_upstream", res.status_code)
        if res.status_code >= 400:
            raise LostAnimalApiError("lost_response", res.status_code)

        try:
            data = res.json()
        except ValueError as exc:
            raise LostAnimalApiError("lost_response", res.status_code) from exc
        response = data.get("response") if isinstance(data, dict) else None
        if not isinstance(response, dict):
            raise LostAnimalApiError("lost_response", res.status_code)
        result_code = str((response.get("header") or {}).get("resultCode", ""))
        if result_code not in ("00", "0", "000"):  # 00 = 정상
            code = {"30": "lost_auth", "22": "lost_rate_limit"}.get(result_code, "lost_response")
            raise LostAnimalApiError(code, res.status_code, result_code)
        return response.get("body") or {}

    async def search(
        self,
        *,
        start: date,
        end: date,
        species: str | None = None,
        region_code: str | None = None,
        org_code: str | None = None,
        sex: str | None = None,
        page: int = 1,
        rows: int = 100,
    ) -> LostPage:
        """분실 날짜(start~end)로 분실 신고를 조회한다.

        species: dog | cat | etc (그 외·None 이면 전체)
        region_code: 시도 코드(upr_cd), org_code: 시군구 코드(org_cd), sex: M | F
        """
        if start > end:
            raise ValueError("start 가 end 보다 늦습니다")
        rows = max(1, min(rows, MAX_ROWS))
        body = await self._get(
            "lossInfo",
            {
                "bgnde": _ymd(start),  # 분실 날짜 검색 시작
                "ended": _ymd(end),  # 분실 날짜 검색 끝
                "upkind": UPKIND.get(species or ""),
                "upr_cd": region_code,
                "org_cd": org_code,
                "sex_cd": sex if sex in ("M", "F") else None,
                "pageNo": page,
                "numOfRows": rows,
            },
        )
        return LostPage(
            items=_items_of(body),
            total_count=_int(body.get("totalCount")),
            page=_int(body.get("pageNo"), page),
            rows=_int(body.get("numOfRows"), rows),
        )
