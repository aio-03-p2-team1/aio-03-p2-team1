"""사진 분석 입력 검증과 API 오류 처리를 시험한다(외부 분석 API 호출 없음)."""

import base64
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.agent.llm import LlmError
from backend.agent.photo import MAX_IMAGE_BYTES, InvalidPhoto, decode_and_validate
from backend.agent.schema import PhotoAnalysisResponse
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
        return PhotoAnalysisResponse(
            animal_present=False,
            identifiable=False,
            center_subject_clear=False,
            suitable=False,
            species="",
            colors=[],
            breed="",
            sex="",
            marks=[],
            message="사진에서 동물을 확인하지 못했어요. 동물이 보이는 사진을 올려 주세요.",
            model="test-model",
            prompt_version="photo-feature-v3",
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
    assert response.json()["message"] == "사진에서 동물을 확인하지 못했어요. 동물이 보이는 사진을 올려 주세요."
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
