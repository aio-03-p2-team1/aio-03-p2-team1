"""실종 정보 게시판 /posts: 공개 읽기, 로그인 작성, 작성자만 삭제, 입력·사진 검증."""

import base64
from datetime import timedelta

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.routers.posts import MAX_PHOTO_BYTES, MAX_POSTS_PER_USER, kst_today

from .conftest import ORIGIN, build_ctx, signup

PNG_1PX = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def body(**over):
    data = {
        "pet_name": "초코",
        "species": "dog",
        "region": "서울특별시",
        "lost_date": (kst_today() - timedelta(days=3)).isoformat(),
        "breed": "푸들",
        "description": "갈색 작은 강아지. 노란 목줄, 강서구 공원 근처에서 마지막으로 봤어요.",
    }
    data.update(over)
    return data


def new_client():
    return TestClient(create_app(build_ctx()), headers={"Origin": ORIGIN})


def test_create_requires_login():
    with new_client() as client:
        assert client.post("/api/v1/posts", json=body()).status_code == 401


def test_list_and_detail_are_public_and_hide_author():
    with new_client() as client:
        signup(client, "a@example.com")
        created = client.post("/api/v1/posts", json=body()).json()
        assert created["mine"] is True
        assert "author" not in created
        client.post("/api/v1/auth/logout")

        listed = client.get("/api/v1/posts").json()
        assert listed["count"] == 1
        item = listed["items"][0]
        assert item["mine"] is False and "author" not in item and "description" not in item
        detail = client.get(f"/api/v1/posts/{created['id']}").json()
        assert detail["description"].startswith("갈색") and detail["mine"] is False


def test_filters_by_species_and_region():
    with new_client() as client:
        signup(client)
        client.post("/api/v1/posts", json=body())
        client.post("/api/v1/posts", json=body(pet_name="나비", species="cat", region="경기도"))
        assert [i["pet_name"] for i in client.get("/api/v1/posts?species=cat").json()["items"]] == ["나비"]
        assert [i["pet_name"] for i in client.get("/api/v1/posts?region=서울특별시").json()["items"]] == ["초코"]
        assert client.get("/api/v1/posts?species=bird").status_code == 422


def test_only_author_can_delete():
    with new_client() as client:
        signup(client, "a@example.com")
        post_id = client.post("/api/v1/posts", json=body()).json()["id"]
        client.post("/api/v1/auth/logout")
        signup(client, "b@example.com")
        res = client.delete(f"/api/v1/posts/{post_id}")
        assert res.status_code == 403 and res.json()["detail"]["code"] == "post_forbidden"
        client.post("/api/v1/auth/logout")
        client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "password123"})
        assert client.delete(f"/api/v1/posts/{post_id}").status_code == 204
        assert client.get(f"/api/v1/posts/{post_id}").status_code == 404


def test_rejects_future_or_old_date_and_blank_fields():
    with new_client() as client:
        signup(client)
        future = (kst_today() + timedelta(days=1)).isoformat()
        assert client.post("/api/v1/posts", json=body(lost_date=future)).json()["detail"]["code"] == "lost_date_future"
        old = (kst_today() - timedelta(days=400)).isoformat()
        assert client.post("/api/v1/posts", json=body(lost_date=old)).json()["detail"]["code"] == "lost_date_too_old"
        assert client.post("/api/v1/posts", json=body(pet_name="   ")).status_code == 422
        assert client.post("/api/v1/posts", json=body(species="all")).status_code == 422
        assert client.get("/api/v1/posts").json()["count"] == 0


def test_photo_round_trip_and_validation():
    with new_client() as client:
        signup(client)
        created = client.post("/api/v1/posts", json=body(photo=f"data:image/png;base64,{PNG_1PX}")).json()
        assert created["has_photo"] is True
        res = client.get(f"/api/v1/posts/{created['id']}/photo")
        assert res.status_code == 200 and res.headers["content-type"] == "image/png"
        assert res.content == base64.b64decode(PNG_1PX)

        bad = client.post("/api/v1/posts", json=body(photo="data:image/svg+xml;base64,PHN2Zz4="))
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "photo_invalid"
        big = base64.b64encode(b"x" * (MAX_PHOTO_BYTES + 1)).decode()
        too_big = client.post("/api/v1/posts", json=body(photo=f"data:image/jpeg;base64,{big}"))
        assert too_big.status_code in (413, 422)

        no_photo = client.post("/api/v1/posts", json=body()).json()
        assert client.get(f"/api/v1/posts/{no_photo['id']}/photo").status_code == 404


def test_unknown_or_malformed_id_is_404():
    with new_client() as client:
        assert client.get("/api/v1/posts/does-not-exist").status_code == 404
        assert client.get("/api/v1/posts/" + "0" * 32).status_code == 404


def test_per_user_post_limit():
    with new_client() as client:
        signup(client)
        for _ in range(MAX_POSTS_PER_USER):
            assert client.post("/api/v1/posts", json=body()).status_code == 201
        res = client.post("/api/v1/posts", json=body())
        assert res.status_code == 429 and res.json()["detail"]["code"] == "post_limit"


def test_create_blocked_from_unknown_origin():
    with new_client() as client:
        signup(client)
        res = client.post("/api/v1/posts", json=body(), headers={"Origin": "https://evil.example"})
        assert res.status_code == 403 and res.json()["detail"]["code"] == "origin_not_allowed"
