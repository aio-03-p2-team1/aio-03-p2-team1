"""실종 전단지 템플릿, 사용자별 문서, Pillow 자산 최적화 API."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from .conftest import signup


def poster_body(**overrides):
    body = {
        "templateId": "basic",
        "width": 794,
        "height": 1123,
        "components": [
            {
                "id": "pet-name",
                "type": "text",
                "label": "동물 이름",
                "fieldKey": "pet_name",
                "content": "보리",
                "x": 50,
                "y": 100,
                "width": 400,
                "height": 50,
                "fontSize": 30,
                "zIndex": 1,
            }
        ],
    }
    body.update(overrides)
    return body


def exif_jpeg():
    image = Image.new("RGB", (10, 20), "red")
    exif = Image.Exif()
    exif[274] = 6  # 세로 이미지를 시계 방향으로 세워 표시
    stream = BytesIO()
    image.save(stream, format="JPEG", exif=exif)
    return stream.getvalue()


def test_templates_are_public_and_have_three_presets(client):
    response = client.get("/api/v1/poster/templates")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["basic", "info", "urgent"]
    detail = client.get("/api/v1/poster/templates/basic")
    assert detail.json()["width"] == 794 and detail.json()["height"] == 1123
    assert detail.json()["components"]
    assert client.get("/api/v1/poster/templates/missing").status_code == 404


def test_poster_crud_is_scoped_to_logged_in_owner(client):
    assert client.post("/api/v1/posters", json=poster_body()).status_code == 401
    signup(client, "poster-a@example.com")
    created = client.post("/api/v1/posters", json=poster_body())
    assert created.status_code == 201
    poster_id = created.json()["id"]
    assert created.json()["components"][0]["content"] == "보리"
    assert client.get(f"/api/v1/posters/{poster_id}").status_code == 200

    updated_body = poster_body(components=[{**poster_body()["components"][0], "content": "초코"}])
    updated = client.put(f"/api/v1/posters/{poster_id}", json=updated_body)
    assert updated.status_code == 200 and updated.json()["components"][0]["content"] == "초코"

    client.post("/api/v1/auth/logout")
    signup(client, "poster-b@example.com")
    assert client.get(f"/api/v1/posters/{poster_id}").status_code == 404
    assert client.put(f"/api/v1/posters/{poster_id}", json=poster_body()).status_code == 404
    assert client.delete(f"/api/v1/posters/{poster_id}").status_code == 404

    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"email": "poster-a@example.com", "password": "password123"})
    assert client.delete(f"/api/v1/posters/{poster_id}").status_code == 204
    assert client.get(f"/api/v1/posters/{poster_id}").status_code == 404


def test_poster_rejects_duplicate_ids_and_invalid_dimensions(client):
    signup(client)
    duplicate = poster_body(components=[poster_body()["components"][0]] * 2)
    response = client.post("/api/v1/posters", json=duplicate)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "poster_component_invalid"

    invalid = poster_body(components=[{**poster_body()["components"][0], "width": 0}])
    assert client.post("/api/v1/posters", json=invalid).json()["detail"]["code"] == "poster_component_invalid"
    assert client.post("/api/v1/posters", json=poster_body(templateId="unknown")).status_code == 422
    invalid_style = poster_body(components=[{**poster_body()["components"][0], "color": {"css": "red"}}])
    assert client.post("/api/v1/posters", json=invalid_style).json()["detail"]["code"] == "poster_component_invalid"


def test_upload_reorients_and_optimizes_image_and_scopes_asset(client):
    assert client.post("/api/v1/poster/assets", files={"file": ("pet.jpg", exif_jpeg(), "image/jpeg")}).status_code == 401
    signup(client, "asset-a@example.com")
    uploaded = client.post("/api/v1/poster/assets", files={"file": ("pet.jpg", exif_jpeg(), "image/jpeg")})
    assert uploaded.status_code == 201
    payload = uploaded.json()
    assert payload["format"] == "webp" and (payload["width"], payload["height"]) == (20, 10)
    result = client.get(f"/api/v1{payload['url']}")
    assert result.status_code == 200 and result.headers["content-type"] == "image/webp"
    optimized = Image.open(BytesIO(result.content))
    assert optimized.format == "WEBP" and optimized.size == (20, 10)
    assert not optimized.getexif()

    client.post("/api/v1/auth/logout")
    signup(client, "asset-b@example.com")
    assert client.get(f"/api/v1{payload['url']}").status_code == 404
    photo = {"id": "photo", "type": "image", "assetId": payload["assetId"], "x": 0, "y": 0, "width": 100, "height": 100}
    unavailable = client.post("/api/v1/posters", json=poster_body(components=[photo]))
    assert unavailable.status_code == 422
    assert unavailable.json()["detail"]["code"] == "poster_asset_unavailable"


def test_upload_rejects_non_image_and_unsupported_real_format(client):
    signup(client)
    invalid = client.post("/api/v1/poster/assets", files={"file": ("fake.png", b"not an image", "image/png")})
    assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "poster_asset_invalid"

    image = Image.new("RGB", (2, 2), "blue")
    stream = BytesIO()
    image.save(stream, format="GIF")
    unsupported = client.post("/api/v1/poster/assets", files={"file": ("pet.gif", stream.getvalue(), "image/gif")})
    assert unsupported.status_code == 415
    assert unsupported.json()["detail"]["code"] == "poster_asset_format"
