"""분실동물 조회 서비스 API 도구 (실종 정보 게시판용).

공식 문서: https://www.data.go.kr/data/15141910/openapi.do
주소: https://apis.data.go.kr/1543061/lossInfoService

| 기능         | 경로               | 필수 요청 변수                    |
| ------------ | ------------------ | --------------------------------- |
| 분실동물 조회 | lossInfo           | serviceKey, bgnde, ended(YYYYMMDD) |
| 시도 조회     | lossInfoSido       | serviceKey                        |
| 시군구 조회   | lossInfoSigungu    | serviceKey, upr_cd                |
| 품종 조회     | lossInfoKind       | serviceKey, up_kind_cd            |

응답 항목 필드(2026-11-14 실제 응답으로 확인, scripts/inspect_lost_api.py)
  happenDt 분실 일시("2026-11-11 10:00:00.0"), happenAddr 분실 주소, happenPlace 분실 장소 설명,
  kindCd 품종 이름("믹스견"), colorCd 색, sexCd 성별(M/F), age 나이("6살"), specialMark 특징(자유 글),
  popfile 사진 주소(http), orgNm 관할 지자체("서울특별시 강동구")
  개인정보 → 사용하지 않음: callName·callTel(신고자), rfidCd(마이크로칩), happenAddrDtl(상세 주소)
  ※ 축종(개·고양이) 필드와 고유 번호가 없다 → 축종은 요청 조건(upkind)으로 붙이고, ID 는 원본 값으로 계산한다.

지켜야 할 것
- 화면용 변환은 normalize_lost() 한 곳에서만 한다. 개인정보 필드는 여기서 버린다(응답·캐시에 남기지 않음).
- 인증 오류·통신 실패를 빈 결과로 바꾸지 않는다(LostAnimalApiError). 빈 결과(0건)와 실패를 구분한다.
- 키 값을 로그·예외 메시지에 넣지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import unquote

import hashlib
import re

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


# ── 화면용 변환 ─────────────────────────────────────────────────────────

# 개인정보라 화면·캐시에 남기지 않는 원본 필드
PRIVATE_FIELDS = ("callName", "callTel", "rfidCd", "happenAddrDtl")

# 특징 글에 섞인 전화번호(010-1234-5678, 01012345678, 02)123-4567, +82 10 … 등)를 가린다.
_PHONE = re.compile(r"(?:\+?82[\s.-]?\(?0?|\(?0)\d{1,2}\)?[\s.-]?\d{3,4}[\s.-]?\d{4}")
CONTACT_MASK = "(연락처 생략)"


def mask_contacts(text: str | None) -> str:
    """자유 글에서 전화번호 형태를 '(연락처 생략)'으로 바꾼다."""
    return _PHONE.sub(CONTACT_MASK, text or "").strip()


def _https(url: str | None) -> str | None:
    # 사진 주소가 http 로 온다. https 배포 화면에서 막히지 않도록 https 로 바꾼다(구조동물 사진과 같은 처리).
    if not url or not str(url).strip():
        return None
    url = str(url).strip()
    return "https://" + url[len("http://"):] if url.startswith("http://") else url


def _iso_date(value: str | None) -> str | None:
    """'2026-11-11 10:00:00.0' 또는 '20261111' → '2026-11-11'. 형식이 다르면 None(지어내지 않음)."""
    text = str(value or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    if re.match(r"^\d{8}$", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return None


def lost_id(raw: dict[str, Any], species: str) -> str | None:
    """원본에 고유 번호가 없어 ID 를 계산한다: 'lost-YYYYMMDD-해시12자리'.

    같은 신고는 항상 같은 ID 가 나온다(분실 일시·사진·주소·품종·특징으로 계산).
    앞부분 날짜는 캐시가 비었을 때 그 날짜만 다시 조회해 상세를 찾는 데 쓴다.
    """
    day = _iso_date(raw.get("happenDt"))
    if not day:
        return None
    basis = "|".join(str(raw.get(k) or "") for k in ("happenDt", "popfile", "happenAddr", "kindCd", "specialMark", "orgNm"))
    digest = hashlib.sha256(f"{species}|{basis}".encode("utf-8")).hexdigest()[:12]
    return f"lost-{day.replace('-', '')}-{digest}"


def normalize_lost(raw: dict[str, Any], species: str) -> dict[str, Any] | None:
    """API 원본 항목 → 게시판 글 형태. 회원 글(_public)과 같은 키를 쓰고, 개인정보 필드는 넣지 않는다.

    species 는 요청에 쓴 축종(dog/cat/etc)이다. 분실 날짜를 읽을 수 없는 항목은 None(목록에서 뺀다).
    """
    item_id = lost_id(raw, species)
    if not item_id:
        return None
    photo = _https(raw.get("popfile"))
    description = mask_contacts(raw.get("specialMark"))
    return {
        "id": item_id,
        "source": "lost_api",  # 공공데이터 분실 신고(회원 글은 "member")
        "pet_name": "",  # 분실 신고에는 이름이 없다
        "species": species,
        "region": str(raw.get("orgNm") or "").strip(),  # 관할 지자체(시도 시군구)
        "lost_place": str(raw.get("happenAddr") or "").strip(),
        "happen_place": str(raw.get("happenPlace") or "").strip(),
        "lost_date": _iso_date(raw.get("happenDt")),
        "breed": str(raw.get("kindCd") or "").strip(),
        "color": str(raw.get("colorCd") or "").strip(),
        "sex": raw.get("sexCd") if raw.get("sexCd") in ("M", "F") else None,
        "age": str(raw.get("age") or "").strip(),
        "photo_url": photo,
        "has_photo": bool(photo),
        "description": description,
        "summary": description if len(description) <= 80 else description[:80] + "…",
        "mine": False,
    }
