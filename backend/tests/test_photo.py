"""사진 분석 입력 검증과 API 오류 처리를 시험한다(외부 분석 API 호출 없음)."""

import base64
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.agent.llm import LlmError
from backend.agent.photo import MAX_IMAGE_BYTES, InvalidPhoto, decode_and_validate
from backend.schemas.llm import PhotoAnalysisResult
from backend.main import create_app

from .conftest import ORIGIN, build_ctx, signup


def image_bytes(image_format="PNG", size=(1, 1)):
    output = BytesIO()
    Image.new("RGB", size, "white").save(output, format=image_format)
    return output.getvalue()


def encoded_image(data):
    return base64.b64encode(data).decode("ascii")


def test_decode_and_validate_accepts_supported_image_formats():
    for image_format, mime_type in (
        ("JPEG", "image/jpeg"),
        ("PNG", "image/png"),
        ("WEBP", "image/webp"),
    ):
        data = image_bytes(image_format)
        assert decode_and_validate(encoded_image(data)) == (data, mime_type)


@pytest.mark.parametrize("encoded", ["", "not-base64!"])
def test_decode_and_validate_rejects_empty_or_invalid_base64(encoded):
    with pytest.raises(InvalidPhoto) as info:
        decode_and_validate(encoded)
    assert info.value.code == "invalid_photo"


def test_decode_and_validate_rejects_unsupported_format():
    with pytest.raises(InvalidPhoto) as info:
        decode_and_validate(encoded_image(image_bytes("BMP")))
    assert info.value.code == "unsupported_photo_format"


def test_decode_and_validate_rejects_payload_over_8mb():
    encoded = "A" * (((MAX_IMAGE_BYTES + 2) // 3) * 4 + 1)
    with pytest.raises(InvalidPhoto) as info:
        decode_and_validate(encoded)
    assert info.value.code == "photo_too_large"


def test_decode_and_validate_rejects_images_over_pixel_limit():
    data = image_bytes("PNG", (5000, 4001))
    with pytest.raises(InvalidPhoto) as info:
        decode_and_validate(encoded_image(data))
    assert info.value.code == "photo_too_many_pixels"


class FakePhotoAnalyzer:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def analyze_photo(self, image_data, mime_type):
        self.calls.append((image_data, mime_type))
        if self.error:
            raise self.error
        return PhotoAnalysisResult(
            animal_present=False,
            identifiable=False,
            center_subject_clear=False,
            suitable=False,
            reason_code="animal_not_detected",
            species="",
            colors=[],
            breed="",
            breed_code="",
            sex="",
            marks=[],
        )


def photo_client(analyzer):
    ctx = build_ctx()
    ctx.photo_llm = analyzer
    return TestClient(create_app(ctx), headers={"Origin": ORIGIN})


def test_photo_analysis_requires_login():
    with photo_client(FakePhotoAnalyzer()) as client:
        response = client.post("/api/v1/photo-analysis", json={"image_base64": encoded_image(image_bytes())})
    assert response.status_code == 401


def test_photo_analysis_validates_format_before_calling_analyzer():
    analyzer = FakePhotoAnalyzer()
    with photo_client(analyzer) as client:
        signup(client)
        response = client.post(
            "/api/v1/photo-analysis", json={"image_base64": encoded_image(image_bytes("BMP"))}
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_photo_format"
    assert analyzer.calls == []


def test_photo_analysis_passes_valid_image_and_returns_unsuitable_result():
    analyzer = FakePhotoAnalyzer()
    data = image_bytes("PNG")
    with photo_client(analyzer) as client:
        signup(client)
        response = client.post("/api/v1/photo-analysis", json={"image_base64": encoded_image(data)})
    assert response.status_code == 200
    assert response.json()["suitable"] is False
    assert response.json()["reason_code"] == "animal_not_detected"
    assert "message" not in response.json()
    assert "model" not in response.json()
    assert "prompt_version" not in response.json()
    assert response.json()["analysis_ms"] >= 0
    assert analyzer.calls == [(data, "image/png")]


def test_photo_analysis_maps_backend_llm_failure_to_api_error():
    analyzer = FakePhotoAnalyzer(LlmError("llm_upstream", "private upstream detail"))
    with photo_client(analyzer) as client:
        signup(client)
        response = client.post(
            "/api/v1/photo-analysis", json={"image_base64": encoded_image(image_bytes())}
        )
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "llm_upstream"
    assert "private upstream detail" not in response.text


# ── 게시글 사진 분석(post_id): 회원 글은 저장된 사진, 분실 신고는 서버가 공공데이터 사진을 받아 분석 ──
import asyncio  # noqa: E402

import httpx  # noqa: E402

from backend.tools import remote_photo  # noqa: E402

LOST_ID = "lost-20261115-0123456789ab"


class FakeLost:
    def __init__(self, items):
        self.items = items

    async def get(self, item_id):
        return self.items.get(item_id)


def test_photo_analysis_body_needs_exactly_one_source():
    with photo_client(FakePhotoAnalyzer()) as client:
        signup(client)
        both = client.post("/api/v1/photo-analysis", json={"image_base64": encoded_image(image_bytes()), "post_id": "x"})
        neither = client.post("/api/v1/photo-analysis", json={})
    assert both.status_code == 422 and neither.status_code == 422


def test_member_post_photo_is_analyzed_by_post_id():
    analyzer = FakePhotoAnalyzer()
    data = image_bytes("JPEG")
    with photo_client(analyzer) as client:
        signup(client)
        ctx = client.app.state.ctx
        photo = {"type": "image/jpeg", "data": encoded_image(data), "bytes": len(data)}
        asyncio.run(ctx.store.put("board", "post", "p" * 32, {"pet_name": "초코", "photo": photo}))
        ok = client.post("/api/v1/photo-analysis", json={"post_id": "p" * 32})
        missing = client.post("/api/v1/photo-analysis", json={"post_id": "q" * 32})
    assert ok.status_code == 200 and analyzer.calls == [(data, "image/jpeg")]
    assert missing.status_code == 404


def test_lost_report_photo_is_fetched_by_server(monkeypatch):
    analyzer = FakePhotoAnalyzer()
    data = image_bytes("JPEG")
    fetched = []

    async def fake_fetch(url, **_):
        fetched.append(url)
        return data

    monkeypatch.setattr(remote_photo, "fetch_photo", fake_fetch)
    url = "https://openapi.animal.go.kr/openapi/service/rest/fileDownloadSrvc/files/loss/a.jpg"
    with photo_client(analyzer) as client:
        signup(client)
        client.app.state.ctx.lost = FakeLost({LOST_ID: {"id": LOST_ID, "photo_url": url}})
        response = client.post("/api/v1/photo-analysis", json={"post_id": LOST_ID})
    assert response.status_code == 200
    assert fetched == [url]  # 사용자가 보낸 주소가 아니라 공공 API 응답의 주소만 받아 온다
    assert analyzer.calls == [(data, "image/jpeg")]


def test_remote_photo_only_allows_public_data_host_and_no_redirect():
    def handler(request):
        if request.url.path.endswith("redirect.jpg"):
            return httpx.Response(302, headers={"location": "https://evil.example/x.jpg"})
        return httpx.Response(200, content=b"img")

    transport = httpx.MockTransport(handler)
    ok = asyncio.run(remote_photo.fetch_photo("https://openapi.animal.go.kr/a.jpg", transport=transport))
    assert ok == b"img"
    for bad in ("http://openapi.animal.go.kr/a.jpg", "https://evil.example/a.jpg", "https://127.0.0.1/a.jpg"):
        with pytest.raises(InvalidPhoto) as info:
            asyncio.run(remote_photo.fetch_photo(bad, transport=transport))
        assert info.value.code == "photo_source_not_allowed"
    with pytest.raises(InvalidPhoto) as info:
        asyncio.run(remote_photo.fetch_photo("https://openapi.animal.go.kr/redirect.jpg", transport=transport))
    assert info.value.code == "photo_fetch_failed"
