"""구조동물 조회 서비스 API 도구.

- 지역 목록: sido_v2, 공고 검색: abandonmentPublic_v2
- 실제 응답에 없는 상세·보호센터 엔드포인트를 만들지 않는다.
  상세·보호센터 정보는 검색 응답 필드에서 정규화한다.
- 인증 오류·통신 실패를 빈 결과나 샘플로 대체하지 않는다(AnimalApiError).
- 키가 없을 때만(=animal_data_source 'sample') 명시적인 샘플 데이터를 쓴다.

응답 필드 이름은 공공데이터포털 v2 문서 기준이다. 실제 키로 응답을 확인하기 전까지는
필드 누락을 '미확인'으로 처리하고 값을 만들어내지 않는다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote

import httpx

UPKIND = {"dog": "417000", "cat": "422400", "etc": "429900"}
UPKIND_REVERSE = {v: k for k, v in UPKIND.items()}
SPECIES_LABEL = {"dog": "개", "cat": "고양이", "etc": "기타", "all": "전체"}
SEX_LABEL = {"M": "수컷", "F": "암컷", "Q": "미상"}


class AnimalApiError(RuntimeError):
    """code: animal_auth · animal_rate_limit · animal_timeout · animal_network · animal_upstream · animal_response"""

    def __init__(self, code: str, status: int | None = None, result_code: str | None = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.result_code = result_code

    @property
    def retryable(self) -> bool:
        return self.code in {"animal_timeout", "animal_network", "animal_upstream", "animal_rate_limit"}


@dataclass
class Region:
    code: str
    name: str


@dataclass
class SearchPage:
    items: list[dict[str, Any]]
    total_count: int
    page: int
    rows: int
    fetched_at: str
    source: str  # "api" | "sample"
    params: dict[str, Any] = field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ymd_to_iso(value: str | None) -> str | None:
    if not value or len(str(value)) != 8 or not str(value).isdigit():
        return None
    v = str(value)
    return f"{v[:4]}-{v[4:6]}-{v[6:]}"


def _https(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if url.startswith("http://"):
        url = "https://" + url[7:]
    return url or None


def short_region_name(full: str) -> str:
    """'서울특별시' → '서울', '경상남도' → '경남' 처럼 화면용 짧은 이름."""
    table = {
        "서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천", "광주": "광주", "대전": "대전",
        "울산": "울산", "세종": "세종", "경기": "경기", "강원": "강원", "충청북": "충북", "충청남": "충남",
        "전라북": "전북", "전북": "전북", "전라남": "전남", "경상북": "경북", "경상남": "경남", "제주": "제주",
    }
    for prefix, short in table.items():
        if full.startswith(prefix):
            return short
    return full


def normalize_item(raw: dict[str, Any], fetched_at: str, source: str = "api") -> dict[str, Any]:
    """API 항목 → 그래프·화면용 공고. 없는 필드는 None 으로 둔다(생성하지 않는다)."""
    up_cd = str(raw.get("upKindCd") or "")
    photos = [p for p in (_https(raw.get("popfile1")), _https(raw.get("popfile2"))) if p]
    return {
        "id": str(raw.get("desertionNo") or ""),
        "notice_no": raw.get("noticeNo"),
        "source": source,
        "species": UPKIND_REVERSE.get(up_cd),
        "kind_name": raw.get("upKindNm"),
        "breed": raw.get("kindNm"),
        "color": raw.get("colorCd"),
        "sex": raw.get("sexCd"),
        "neuter": raw.get("neuterYn"),
        "age": raw.get("age"),
        "weight": raw.get("weight"),
        "happen_date": _ymd_to_iso(raw.get("happenDt")),
        "happen_place": raw.get("happenPlace"),
        "special_mark": raw.get("specialMark"),
        "process_state": raw.get("processState"),
        "notice_start": _ymd_to_iso(raw.get("noticeSdt")),
        "notice_end": _ymd_to_iso(raw.get("noticeEdt")),
        "photos": photos,
        "sample_photo": raw.get("_samplePhoto"),
        "care": {
            "name": raw.get("careNm"),
            "tel": raw.get("careTel"),
            "address": raw.get("careAddr"),
            "org": raw.get("orgNm"),
        },
        "updated_at": raw.get("updTm"),
        "fetched_at": fetched_at,
    }


def _items_of(body: dict[str, Any]) -> list[dict[str, Any]]:
    items = body.get("items")
    if not items:  # 빈 결과는 "" 또는 None 으로 온다
        return []
    item = items.get("item") if isinstance(items, dict) else None
    if item is None:
        return []
    return item if isinstance(item, list) else [item]


class AnimalApi:
    """실제 API 클라이언트. transport 는 테스트에서 모의 응답을 넣을 때 쓴다."""

    source = "api"

    def __init__(self, base_url: str, service_key: str, timeout: float = 20, transport=None):
        # 일반 키와 URL 인코딩 키 모두 처리: 인코딩된 키는 한 번 풀어서 httpx 가 다시 인코딩하게 한다.
        key = service_key.strip()
        if "%" in key:
            key = unquote(key)
        self._key = key
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)
        self._regions: tuple[float, list[Region]] | None = None

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {"serviceKey": self._key, "_type": "json", **{k: v for k, v in params.items() if v is not None}}
        try:
            res = await self._client.get("/" + path, params=query)
        except httpx.TimeoutException as exc:
            raise AnimalApiError("animal_timeout") from exc
        except httpx.HTTPError as exc:
            raise AnimalApiError("animal_network") from exc
        text = res.text
        if res.status_code in (401, 403) or "SERVICE_KEY_IS_NOT_REGISTERED" in text:
            raise AnimalApiError("animal_auth", res.status_code, "30" if "NOT_REGISTERED" in text else None)
        if res.status_code == 429 or "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in text:
            raise AnimalApiError("animal_rate_limit", res.status_code, "22")
        if res.status_code >= 500:
            raise AnimalApiError("animal_upstream", res.status_code)
        if res.status_code >= 400:
            raise AnimalApiError("animal_response", res.status_code)
        try:
            data = res.json()
        except ValueError as exc:
            raise AnimalApiError("animal_response", res.status_code) from exc
        response = data.get("response") if isinstance(data, dict) else None
        if not isinstance(response, dict):
            raise AnimalApiError("animal_response", res.status_code)
        header = response.get("header") or {}
        result_code = str(header.get("resultCode", ""))
        if result_code not in ("00", "0", "000"):
            code = {"30": "animal_auth", "22": "animal_rate_limit"}.get(result_code, "animal_response")
            raise AnimalApiError(code, res.status_code, result_code)
        return response.get("body") or {}

    async def regions(self) -> list[Region]:
        if self._regions and time.monotonic() - self._regions[0] < 3600:
            return self._regions[1]
        body = await self._get("sido_v2", {"numOfRows": 30, "pageNo": 1})
        regions = [
            Region(code=str(i.get("orgCd")), name=str(i.get("orgdownNm")))
            for i in _items_of(body)
            if i.get("orgCd") and i.get("orgdownNm")
        ]
        if not regions:
            raise AnimalApiError("animal_response")
        self._regions = (time.monotonic(), regions)
        return regions

    async def search(
        self,
        *,
        region_code: str | None,
        start: date,
        end: date,
        species: str,
        page: int = 1,
        rows: int = 50,
    ) -> SearchPage:
        params = {
            "bgnde": start.strftime("%Y%m%d"),
            "endde": end.strftime("%Y%m%d"),
            "upkind": UPKIND.get(species),  # 'all' 이면 None → 축종 필터 생략
            "upr_cd": region_code,
            "pageNo": page,
            "numOfRows": rows,
        }
        body = await self._get("abandonmentPublic_v2", params)
        fetched = _now_iso()
        items = [normalize_item(i, fetched) for i in _items_of(body)]
        try:
            total = int(body.get("totalCount") or 0)
        except (TypeError, ValueError):
            total = len(items)
        return SearchPage(items=items, total_count=total, page=page, rows=rows, fetched_at=fetched, source="api", params=params)


# ---------------------------------------------------------------------------
# 샘플 데이터: ANIMAL_API_KEY 가 없을 때만 사용하며 화면에 '샘플'로 표시한다.
# 공고 번호·연락처는 실제 값처럼 보이지 않도록 SAMPLE- 접두사와 빈 연락처를 쓴다.
# ---------------------------------------------------------------------------

SAMPLE_REGIONS = [Region(code=f"sample-{n}", name=n) for n in ("서울특별시", "경기도", "인천광역시", "부산광역시", "대전광역시", "광주광역시", "울산광역시")]

_SAMPLE_ROWS = [
    # photo, upKindCd, kindNm, sex, color, region, place, days_ago, special
    (0, "417000", "푸들 믹스", "F", "갈색", "서울특별시", "서울 강서구 공원", 2, "갈색 곱슬털의 소형견, 회색 목줄 착용"),
    (1, "417000", "믹스견", "M", "아이보리", "경기도", "경기 수원시 거리", 3, "아이보리색 털의 어린 강아지, 작은 체구"),
    (2, "417000", "말티푸 믹스", "F", "회색·흰색", "부산광역시", "부산 해운대구", 4, "회색과 흰색이 섞인 털, 중소형견"),
    (3, "417000", "리트리버 믹스", "M", "크림색", "인천광역시", "인천 연수구 산책로", 5, "연한 크림색 털, 귀가 늘어진 강아지"),
    (4, "422400", "코리안 숏헤어", "F", "흰색·검은색", "대전광역시", "대전 유성구", 6, "흰색 바탕에 검은 무늬, 몸에 상처 부위가 있음"),
    (5, "417000", "장모 믹스견", "F", "연갈색", "광주광역시", "광주 서구 거리", 7, "갈색 장모, 큰 눈의 소형견"),
    (6, "422400", "코리안 숏헤어", "M", "주황색·흰색", "울산광역시", "울산 남구", 7, "주황색과 흰색 털, 성묘로 추정"),
    (7, "417000", "푸들 믹스", "M", "연갈색", "경기도", "경기 고양시", 8, "연한 갈색 곱슬털, 중형견 크기"),
]


def sample_items(today: date | None = None) -> list[dict[str, Any]]:
    today = today or date.today()
    rows = []
    for index, (photo, up, kind, sex, color, region, place, days, special) in enumerate(_SAMPLE_ROWS, start=1):
        happen = (today - timedelta(days=days)).strftime("%Y%m%d")
        rows.append(
            {
                "desertionNo": f"SAMPLE-{index:03d}",
                "noticeNo": f"SAMPLE-공고-{index:03d}",
                "upKindCd": up,
                "upKindNm": "개" if up == "417000" else "고양이",
                "kindNm": kind,
                "sexCd": sex,
                "colorCd": color,
                "happenDt": happen,
                "happenPlace": place,
                "specialMark": special,
                "processState": "보호중",
                "careNm": "샘플 보호센터",
                "careTel": None,
                "careAddr": None,
                "orgNm": region,
                "_samplePhoto": photo,
                "_region": region,
            }
        )
    return rows


class SampleAnimalApi:
    """키가 없을 때 쓰는 샘플 소스. 필터는 실제 API 와 같은 의미로 적용한다."""

    source = "sample"

    async def regions(self) -> list[Region]:
        return SAMPLE_REGIONS

    async def search(self, *, region_code, start, end, species, page=1, rows=50) -> SearchPage:
        fetched = _now_iso()
        region_name = next((r.name for r in SAMPLE_REGIONS if r.code == region_code), None)
        matched = []
        for raw in sample_items():
            happen = datetime.strptime(raw["happenDt"], "%Y%m%d").date()
            if species != "all" and raw["upKindCd"] != UPKIND.get(species):
                continue
            if region_name and raw["_region"] != region_name:
                continue
            if not (start <= happen <= end):
                continue
            matched.append(normalize_item(raw, fetched, source="sample"))
        chunk = matched[(page - 1) * rows : page * rows]
        return SearchPage(items=chunk, total_count=len(matched), page=page, rows=rows, fetched_at=fetched, source="sample")
