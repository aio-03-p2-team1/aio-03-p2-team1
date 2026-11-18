"""사진 분석 입력 검증과 API 오류 처리를 시험한다(외부 분석 API 호출 없음)."""

import base64
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.agent.llm import LlmError
from backend.agent.photo import MAX_IMAGE_BYTES, InvalidPhoto, decode_and_validate
from backend.agent import refinement_store
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


class FakeTextRefiner:
    def __init__(self):
        self.calls = []

    async def refine_description(self, description, image_data=None, mime_type=None):
        self.calls.append((description, image_data, mime_type))
        from backend.schemas.llm import RefinedDescriptionResult
        return RefinedDescriptionResult(
            description="[털색]: 흰색\n[특징]: 빨간 목줄\n[상황]: 서울에서 실종",
            features={"colors": ["흰색"], "sex": "", "marks": ["빨간 목줄"]},
            photo_features=None,
            prompt_version="feature-refine-v1",
        )


def test_refinement_is_reused_by_search_without_a_second_feature_extraction():
    refiner = FakeTextRefiner()

    class UnexpectedExtractor:
        model = "fake"

        async def extract(self, description):
            raise AssertionError("search graph must use the stored refinement features")

    class UnexpectedSearchAgent:
        async def step(self, messages):
            raise AssertionError("refinement searches must not invoke a second LLM")

    ctx = build_ctx(llm=UnexpectedExtractor(), search_agent=UnexpectedSearchAgent())
    ctx.photo_llm = refiner
    client = TestClient(create_app(ctx), headers={"Origin": ORIGIN})
    with client:
        signup(client)
        refined = client.post("/api/v1/searches/refine", json={"description": "흰색 강아지, 빨간 목줄"})
        assert refined.status_code == 200
        assert refined.json()["description"] == "[털색]: 흰색\n[특징]: 빨간 목줄\n[상황]: 서울에서 실종"
        run = client.post("/api/v1/searches", json={
            "criteria": {"species": "dog", "region": "전체", "lost_date": "2026-11-17",
                         "description": refined.json()["description"]},
            "refinement_id": refined.json()["refinement_id"],
        })
    assert run.status_code == 200
    assert run.json()["criteria"]["description"] == refined.json()["description"]
    assert run.json()["llm_features"]["colors"] == ["흰색"]
    assert len(refiner.calls) == 1


def test_refinement_photo_retrieval_error_falls_back_to_text_in_one_call():
    refiner = FakeTextRefiner()
    ctx = build_ctx()
    ctx.photo_llm = refiner
    client = TestClient(create_app(ctx), headers={"Origin": ORIGIN})
    with client:
        signup(client)
        response = client.post("/api/v1/searches/refine", json={"description": "갈색 고양이", "post_id": "missing-post"})
    assert response.status_code == 200
    assert response.json()["photo_used"] is False
    assert refiner.calls == [("갈색 고양이", None, None)]


def test_refinement_lock_uses_original_text_hash_until_task_finishes():
    import asyncio
    import fakeredis

    async def scenario():
        redis = fakeredis.FakeAsyncRedis()
        assert refinement_store.source_hash("흰 강아지") != refinement_store.source_hash(" 흰 강아지 ")
        assert await refinement_store.begin(redis, "owner", "흰 강아지", "first")
        assert not await refinement_store.begin(redis, "owner", "흰 강아지", "second")
        assert await refinement_store.begin(redis, "other-owner", "흰 강아지", "third")
        await refinement_store.finish(redis, "owner", "흰 강아지", "first")
        assert await refinement_store.begin(redis, "owner", "흰 강아지", "fourth")

    asyncio.run(scenario())


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


def test_photo_analysis_returns_id_and_search_uses_stored_result():
    from backend.agent import photo_store as store

    with photo_client(FakePhotoAnalyzer()) as client:
        signup(client)
        response = client.post("/api/v1/photo-analysis", json={"image_base64": encoded_image(image_bytes())})
        analysis_id = response.json()["analysis_id"]
        assert analysis_id and len(analysis_id) == 32
        ctx = client.app.state.ctx
        assert asyncio.run(store.load(ctx.sessions._redis, next(iter(_owners(ctx))), analysis_id)) is not None
        bad = client.post("/api/v1/searches", json={"criteria": {}, "photo_analysis_id": "not-an-id"})
    assert bad.status_code == 422  # 번호 형식이 틀리면 거절


def _owners(ctx):
    keys = asyncio.run(ctx.sessions._redis.keys("photo-analysis:*"))
    return {k.decode().split(":")[1] for k in keys}


# ── 분석 전 사진 줄이기 ──
def test_shrink_for_analysis_reduces_large_photo_to_1024_jpeg():
    from io import BytesIO

    from PIL import Image

    from backend.agent.photo import shrink_for_analysis

    big = image_bytes("PNG", size=(3000, 2000))
    data, mime = shrink_for_analysis(big, "image/png")
    with Image.open(BytesIO(data)) as image:
        assert mime == "image/jpeg" and image.format == "JPEG" and max(image.size) == 1024
        assert image.size == (1024, 683)  # 비율 유지
    small = image_bytes("PNG", size=(800, 600))
    assert shrink_for_analysis(small, "image/png") == (small, "image/png")  # 작은 사진은 그대로


def test_shrink_for_analysis_applies_exif_rotation_and_white_background():
    from io import BytesIO

    from PIL import Image

    from backend.agent.photo import shrink_for_analysis

    rotated = BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6  # 휴대폰 사진: 90도 돌려서 보라는 표시
    Image.new("RGB", (2000, 1000), (200, 50, 50)).save(rotated, format="JPEG", exif=exif)
    data, _ = shrink_for_analysis(rotated.getvalue(), "image/jpeg")
    with Image.open(BytesIO(data)) as image:
        assert image.size == (512, 1024)  # 세로로 돌린 뒤 줄임

    clear = BytesIO()
    Image.new("RGBA", (2000, 2000), (0, 0, 0, 0)).save(clear, format="PNG")
    data, _ = shrink_for_analysis(clear.getvalue(), "image/png")
    with Image.open(BytesIO(data)) as image:
        assert image.getpixel((10, 10)) == (255, 255, 255)  # 투명 부분은 흰색
