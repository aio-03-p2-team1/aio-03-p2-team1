"""공공데이터 분실 신고 사진을 서버가 대신 받아 온다(사진 분석용).

브라우저는 공공데이터 서버(openapi.animal.go.kr)의 사진을 화면에 보여 줄 수는 있지만, 교차 출처 제한으로
파일 내용을 읽지 못해 사진 분석 요청에 담을 수 없다. 그래서 서버가 받는다.

임의 주소를 받아 오는 통로가 되지 않도록(SSRF 방지):
- 사용자가 보낸 주소는 받지 않는다. 호출하는 쪽이 분실 신고 ID 로 공공 API 응답에서 꺼낸 주소만 넘긴다.
- https + 허용 호스트(ALLOWED_HOSTS)만, 리다이렉트는 따라가지 않는다.
- 크기(8MB)·시간(10초)을 제한하고, 받은 뒤 이미지 검증(decode_and_validate 와 같은 규칙)을 한다.
"""

from __future__ import annotations

import httpx

from backend.agent.photo import InvalidPhoto
from backend.schemas.common import MAX_IMAGE_BYTES

ALLOWED_HOSTS = {"openapi.animal.go.kr"}  # 분실 신고 사진(popfile) 호스트. 2026-11-17 배포 사이트 응답에서 확인
TIMEOUT_SECONDS = 10.0


async def fetch_photo(url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> bytes:
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError) as exc:
        raise InvalidPhoto("photo_source_not_allowed", "이 사진은 가져올 수 없어요.") from exc
    if parsed.scheme != "https" or parsed.host not in ALLOWED_HOSTS:
        raise InvalidPhoto("photo_source_not_allowed", "이 사진은 가져올 수 없어요.")
    data = bytearray()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=transport) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise InvalidPhoto("photo_fetch_failed", "게시글 사진을 가져오지 못했어요.")
                async for chunk in response.aiter_bytes():
                    data += chunk
                    if len(data) > MAX_IMAGE_BYTES:
                        raise InvalidPhoto("photo_too_large", "사진은 8MB 이하만 분석할 수 있어요.")
    except httpx.HTTPError as exc:
        raise InvalidPhoto("photo_fetch_failed", "게시글 사진을 가져오지 못했어요.") from exc
    if not data:
        raise InvalidPhoto("photo_fetch_failed", "게시글 사진을 가져오지 못했어요.")
    return bytes(data)
