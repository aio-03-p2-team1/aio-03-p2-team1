from __future__ import annotations

import httpx

KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"


class KakaoError(RuntimeError):

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


def _valid_coord(lat: float, lng: float) -> bool:
    # 대한민국 대략 범위. 범위를 벗어나면 마커를 찍지 않는다.
    return 32.0 <= lat <= 39.5 and 124.0 <= lng <= 132.5


class KakaoGeocoder:
    def __init__(self, rest_key: str | None, timeout: float = 10, transport=None):
        self._key = rest_key
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def geocode(self, address: str | None) -> dict:
        if not address or not address.strip():
            return {"status": "unavailable", "reason": "address_missing"}
        if not self._key:
            return {"status": "unavailable", "reason": "not_configured"}
        try:
            res = await self._client.get(
                KAKAO_ADDRESS_URL,
                params={"query": address.strip()},
                headers={"Authorization": f"KakaoAK {self._key}"},
            )
        except httpx.TimeoutException as exc:
            raise KakaoError("location_timeout") from exc
        except httpx.HTTPError as exc:
            raise KakaoError("location_network") from exc
        if res.status_code in (401, 403):
            raise KakaoError("location_auth", res.status_code)
        if res.status_code == 429:
            raise KakaoError("location_rate_limit", res.status_code)
        if res.status_code >= 400:
            raise KakaoError("location_response", res.status_code)
        try:
            documents = res.json().get("documents")
        except ValueError as exc:
            raise KakaoError("location_response", res.status_code) from exc
        if not isinstance(documents, list):
            raise KakaoError("location_response", res.status_code)
        if not documents:
            return {"status": "unavailable", "reason": "address_not_found"}
        if len(documents) > 1:
            return {"status": "unavailable", "reason": "address_ambiguous"}
        try:
            lng = float(documents[0]["x"])
            lat = float(documents[0]["y"])
        except (KeyError, TypeError, ValueError):
            return {"status": "unavailable", "reason": "invalid_coordinates"}
        if not _valid_coord(lat, lng):
            return {"status": "unavailable", "reason": "invalid_coordinates"}
        return {"status": "ok", "lat": lat, "lng": lng, "source": "kakao_local_address", "address": address.strip()}
