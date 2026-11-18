"""게시판 글 사진 → 전단지 자산 복사(POST /poster/assets/from-post). 외부 사진은 모의 transport 로 시험한다(실제 호출 없음)."""

import asyncio
import base64
import io
from datetime import timedelta

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import create_app
from backend.routers.posts import kst_today
from backend.tools.lost_animal_api import LostAnimalApi, LostAnimalApiError, normalize_lost
from backend.tools.lost_feed import LostFeed

from .conftest import ORIGIN, build_ctx, signup
from .test_lost_board import FakeLostApi, raw


def jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 120, 60)).save(buf, format="JPEG")
    return buf.getvalue()


class PhotoLostApi(FakeLostApi):
    def __init__(self, *args, photo=None, photo_error=None, **kw):
        super().__init__(*args, **kw)
        self.photo, self.photo_error, self.photo_urls = photo, photo_error, []

    async def fetch_photo(self, url, max_bytes):
        self.photo_urls.append(url)
        if self.photo_error:
            raise LostAnimalApiError(self.photo_error)
        return self.photo


def make(api=None):
    ctx = build_ctx()
    ctx.lost = LostFeed(api) if api is not None else None
    return ctx, TestClient(create_app(ctx), headers={"Origin": ORIGIN})


def test_member_post_photo_copied_to_owner_asset():
    _, client = make()
    with client:
        signup(client, "a@example.com")
        photo = "data:image/jpeg;base64," + base64.b64encode(jpeg()).decode()
        post = client.post("/api/v1/posts", json={
            "pet_name": "초코", "species": "dog", "region": "서울특별시", "breed": "푸들",
            "lost_date": (kst_today() - timedelta(days=1)).isoformat(), "description": "갈색 작은 강아지", "photo": photo,
        }).json()
        res = client.post("/api/v1/poster/assets/from-post", json={"postId": post["id"]})
        assert res.status_code == 201, res.text
        asset = res.json()
        assert (asset["width"], asset["height"], asset["format"]) == (40, 30, "webp")
        assert client.get(f"/api/v1/poster/assets/{asset['assetId']}").headers["content-type"] == "image/webp"
        # 사진 없는 글, 없는 글, 로그인 안 함
        bare = client.post("/api/v1/posts", json={
            "pet_name": "보리", "species": "cat", "region": "서울특별시",
            "lost_date": kst_today().isoformat(), "description": "회색 고양이",
        }).json()
        assert client.post("/api/v1/poster/assets/from-post", json={"postId": bare["id"]}).status_code == 404
        assert client.post("/api/v1/poster/assets/from-post", json={"postId": "0" * 32}).status_code == 404
        assert client.post("/api/v1/poster/assets/from-post", json={"postId": "x", "url": "https://evil"}).status_code == 422
        client.post("/api/v1/auth/logout")
        assert client.post("/api/v1/poster/assets/from-post", json={"postId": post["id"]}).status_code == 401


def test_lost_report_photo_fetched_by_server_from_report_url():
    api = PhotoLostApi({"dog": [raw(1)]}, photo=jpeg())
    _, client = make(api)
    with client:
        signup(client)
        lost = normalize_lost(raw(1), "dog")
        res = client.post("/api/v1/poster/assets/from-post", json={"postId": lost["id"]})
        assert res.status_code == 201, res.text
        assert api.photo_urls == [lost["photo_url"]]


def test_lost_report_photo_failure_is_502_not_fake_photo():
    api = PhotoLostApi({"dog": [raw(1)]}, photo_error="lost_network")
    _, client = make(api)
    with client:
        signup(client)
        res = client.post("/api/v1/poster/assets/from-post", json={"postId": normalize_lost(raw(1), "dog")["id"]})
        assert res.status_code == 502 and res.json()["detail"]["code"] == "poster_photo_unavailable"


def test_fetch_photo_allows_only_animal_go_kr_and_falls_back_to_http():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.scheme == "https":
            raise httpx.ConnectError("bad cert", request=request)
        return httpx.Response(200, content=b"img")

    async def go():
        api = LostAnimalApi("https://apis.example", "k", transport=httpx.MockTransport(handler))
        try:
            got = await api.fetch_photo("https://openapi.animal.go.kr/openapi/service/rest/fileDownloadSrc.jsp?fileName=1.jpg", 100)
            for bad in ("https://evil.example/a.jpg", "https://animal.go.kr.evil.example/a.jpg", "file:///etc/passwd", ""):
                try:
                    await api.fetch_photo(bad, 100)
                    raise AssertionError(bad)
                except LostAnimalApiError as exc:
                    assert exc.code == "lost_photo_host"
            try:
                await api.fetch_photo("http://www.animal.go.kr/big.jpg", 2)
                raise AssertionError("size")
            except LostAnimalApiError as exc:
                assert exc.code == "lost_photo_too_large"
            return got
        finally:
            await api.aclose()

    assert asyncio.run(go()) == b"img"
    assert seen[0].startswith("https://openapi.animal.go.kr") and seen[1].startswith("http://openapi.animal.go.kr")
