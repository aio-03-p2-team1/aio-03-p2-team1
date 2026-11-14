from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from backend.main import create_app

from .conftest import ORIGIN, build_ctx, signup


def test_register_me_logout_flow(client):
    res = signup(client)
    assert res.json() == {"name": "보리 보호자", "email": "bori@example.com"}
    cookie = res.headers["set-cookie"]
    assert "meet_again_session=" in cookie and "HttpOnly" in cookie and "Path=/api/v1" in cookie
    assert "token" not in res.text
    assert client.get("/api/v1/auth/me").json()["email"] == "bori@example.com"
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_duplicate_email_rejected(client):
    signup(client)
    res = client.post("/api/v1/auth/register", json={"name": "x", "email": "BORI@example.com", "password": "password123"})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "email_taken"


def test_login_same_message_for_unknown_email_and_wrong_password(client):
    signup(client)
    client.post("/api/v1/auth/logout")
    wrong = client.post("/api/v1/auth/login", json={"email": "bori@example.com", "password": "nope-nope"})
    unknown = client.post("/api/v1/auth/login", json={"email": "who@example.com", "password": "nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"]["message"] == unknown.json()["detail"]["message"]
    ok = client.post("/api/v1/auth/login", json={"email": "bori@example.com", "password": "password123"})
    assert ok.status_code == 200


def test_login_rotates_session(client):
    signup(client)
    old = client.cookies.get("meet_again_session")
    client.post("/api/v1/auth/login", json={"email": "bori@example.com", "password": "password123"})
    new = client.cookies.get("meet_again_session")
    assert old != new
    client.cookies.clear()
    client.cookies.set("meet_again_session", old)
    assert client.get("/api/v1/auth/me").status_code == 401  # 이전 세션은 폐기됨


def test_validation_error_does_not_echo_password(client):
    res = client.post("/api/v1/auth/register", json={"name": "a", "email": "a@example.com", "password": "short7!"})
    assert res.status_code == 422
    assert "short7!" not in res.text


def test_disallowed_origin_blocked(ctx):
    with TestClient(create_app(ctx), headers={"Origin": "https://evil.example"}) as c:
        res = c.post("/api/v1/auth/register", json={"name": "a", "email": "a@example.com", "password": "password123"})
    assert res.status_code == 403 and res.json()["detail"]["code"] == "origin_not_allowed"


def test_no_store_header(client):
    assert client.get("/api/v1/health").headers["cache-control"] == "no-store"


class DownRedis:
    async def _fail(self, *a, **k):
        raise RedisConnectionError("down")

    set = get = delete = incr = expire = _fail


def test_redis_down_returns_503_not_bypass():
    ctx = build_ctx(redis=DownRedis())
    with TestClient(create_app(ctx), headers={"Origin": ORIGIN}) as c:
        res = c.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "password123"})
        assert res.status_code == 503 and res.json()["detail"]["code"] == "auth_unavailable"
        c.cookies.set("meet_again_session", "anything", path="/api/v1")
        assert c.get("/api/v1/auth/me").status_code == 503


def test_health_reports_sample_source(client):
    body = client.get("/api/v1/health").json()
    assert body["animal_data_source"] == "sample" and body["mode"] == "local"
