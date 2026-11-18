"""관리자 API: 권한, 사용자 정지, 실행 내역·에이전트 집계, 게시물·댓글·전단지 삭제, 로그, 관리자 계정 스크립트."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from fastapi.testclient import TestClient

from backend import admin_log
from backend.auth.sessions import owner_key
from backend.main import create_app
from backend.routers.admin import agent_stats
from backend.routers.posts import kst_today
from backend.storage.sqlite import SqliteStore

from .conftest import ORIGIN, build_ctx, signup
from .test_posters import poster_body

ADMIN = "admin@example.com"


def make():
    ctx = build_ctx()
    return ctx, TestClient(create_app(ctx), headers={"Origin": ORIGIN})


def promote(ctx, email=ADMIN):
    async def go():
        owner = owner_key(email)
        account = await ctx.store.get(owner, "identity", "account")
        account["role"] = "admin"
        await ctx.store.put(owner, "identity", "account", account)
    asyncio.run(go())


def login(client, email, password="password123"):
    client.post("/api/v1/auth/logout")
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


def run_doc(**over):
    run = {
        "run_id": "r" * 32, "thread_id": "t" * 32, "status": "completed", "end_reason": "ok", "criteria": {"species": "dog"},
        "reflection_enabled": True, "reflection_count": 1, "retry_count": 0, "cache_hit": False, "elapsed_ms": 1200,
        "tool_calls": [{"tool": "animal_search", "outcome": "ok"}, {"tool": "kakao_geocode", "outcome": "location_timeout"}],
        "confidence": {"low": True, "reasons": ["few_features"]},
        "agent_decision": {"source": "llm", "final_tool": "finish", "steps": 2, "reruns": 1,
                           "log": [{"step": "start"}, {"step": 0, "tool": "update_features", "ok": False, "rejected": "근거 없음"},
                                   {"step": 1, "tool": "finish", "ok": True}]},
        "issues": [{"type": "duplicates"}], "reflections": [{"issue": "duplicates"}],
        "candidates": [{"id": f"c{i}", "score": 0.1} for i in range(30)], "created_at": "2026-11-18T00:00:00+00:00",
    }
    run.update(over)
    return run


def test_admin_routes_need_admin_role():
    ctx, client = make()
    with client:
        assert client.get("/api/v1/admin/overview").status_code == 401
        signup(client, "user@example.com")
        assert client.get("/api/v1/auth/me").json()["is_admin"] is False
        assert client.get("/api/v1/admin/overview").status_code == 403
        assert client.get("/api/v1/admin/users").status_code == 403
        # 가입 요청에 role 을 넣어도 관리자가 되지 않는다(422: 알 수 없는 필드 또는 무시)
        client.post("/api/v1/auth/logout")
        res = client.post("/api/v1/auth/register", json={"name": "x", "email": "x@example.com", "password": "password123",
                                                         "role": "admin"})
        if res.status_code == 201:
            assert client.get("/api/v1/auth/me").json()["is_admin"] is False
        signup_admin(client, ctx)
        assert client.get("/api/v1/auth/me").json()["is_admin"] is True
        body = client.get("/api/v1/admin/overview").json()
        assert body["checks"]["store"]["ok"] is True and body["checks"]["redis"]["ok"] is True
        assert "search_agent" in body["integrations"] and body["limits"]["agent_max_steps"] >= 1


def signup_admin(client, ctx):
    client.post("/api/v1/auth/logout")
    signup(client, ADMIN, name="관리자")
    promote(ctx)
    return login(client, ADMIN)


def test_disable_user_blocks_login_and_admin_is_protected():
    ctx, client = make()
    with client:
        signup(client, "user@example.com")
        signup_admin(client, ctx)
        users = client.get("/api/v1/admin/users").json()["items"]
        target = next(u for u in users if u["email"] == "user@example.com")
        me = next(u for u in users if u["email"] == ADMIN)
        assert me["role"] == "admin" and "password_hash" not in target
        assert client.patch(f"/api/v1/admin/users/{me['owner']}", json={"disabled": True}).status_code == 422
        assert client.patch(f"/api/v1/admin/users/{target['owner']}", json={"disabled": True}).json()["disabled"] is True
        client.post("/api/v1/auth/logout")
        res = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "password123"})
        assert res.status_code == 403 and res.json()["detail"]["code"] == "account_disabled"
        # 비밀번호가 틀리면 정지 여부를 알리지 않는다
        res = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "wrong-pass"})
        assert res.status_code == 401
        login(client, ADMIN)
        client.patch(f"/api/v1/admin/users/{target['owner']}", json={"disabled": False})
        login(client, "user@example.com")


def test_runs_list_detail_stats_and_delete():
    ctx, client = make()
    with client:
        signup(client, "user@example.com")
        owner = owner_key("user@example.com")
        asyncio.run(ctx.store.put(owner, "run", "a" * 32, run_doc()))
        asyncio.run(ctx.store.put(owner, "run", "b" * 32, run_doc(reflection_enabled=False, reflection_count=0,
                                                                  status="failed", agent_decision=None, confidence=None)))
        signup_admin(client, ctx)
        items = client.get("/api/v1/admin/runs").json()["items"]
        assert len(items) == 2 and {i["email"] for i in items} == {"user@example.com"}
        assert "candidates" not in items[0]
        detail = client.get(f"/api/v1/admin/runs/{owner}/{'a' * 32}").json()
        assert detail["run"]["candidate_count"] == 30 and len(detail["run"]["top_candidates"]) == 20
        stats = client.get("/api/v1/admin/agent/stats").json()
        assert stats["scanned"] == 2 and stats["status"] == {"completed": 1, "failed": 1}
        assert stats["agent"]["rejected"] == {"update_features": 1} and stats["confidence"]["reasons"] == {"few_features": 1}
        assert stats["tool_fail"] == {"kakao_geocode": 2}
        assert stats["reflection_compare"]["on"]["completed_rate"] == 1.0
        assert stats["reflection_compare"]["off"]["completed_rate"] == 0.0
        assert client.delete(f"/api/v1/admin/runs/{owner}/{'a' * 32}").status_code == 204
        assert client.delete(f"/api/v1/admin/runs/{owner}/{'a' * 32}").status_code == 404
        assert client.get(f"/api/v1/admin/runs/not-owner/{'a' * 32}").status_code == 404


def test_agent_stats_excludes_cache_hits_from_tool_counts():
    stats = agent_stats([run_doc(), run_doc(cache_hit=True)])
    assert stats["cache_hit_rate"] == 0.5 and stats["executed_runs"] == 1
    assert stats["tool_use"] == {"animal_search": 1, "kakao_geocode": 1}


def test_admin_deletes_posts_comments_and_posters():
    ctx, client = make()
    with client:
        signup(client, "user@example.com")
        post = client.post("/api/v1/posts", json={
            "pet_name": "초코", "species": "dog", "region": "서울특별시", "breed": "푸들",
            "lost_date": (kst_today() - timedelta(days=1)).isoformat(), "description": "갈색 작은 강아지",
        }).json()
        comment = client.post(f"/api/v1/posts/{post['id']}/comments", json={"body": "봤어요"}).json()
        poster = client.post("/api/v1/posters", json=poster_body()).json()
        owner = owner_key("user@example.com")
        signup_admin(client, ctx)

        posts = client.get("/api/v1/admin/posts").json()["items"]
        assert posts[0]["author"]["email"] == "user@example.com"
        comments = client.get("/api/v1/admin/comments").json()["items"]
        assert comments[0]["post_id"] == post["id"] and comments[0]["body"] == "봤어요"
        posters = client.get("/api/v1/admin/posters").json()["items"]
        assert posters[0]["pet_name"] == "보리" and posters[0]["author"]["owner"] == owner

        assert client.delete(f"/api/v1/admin/comments/{post['id']}/{comment['id']}").status_code == 204
        assert client.get("/api/v1/admin/comments").json()["count"] == 0
        assert client.delete(f"/api/v1/admin/posters/{owner}/{poster['id']}").status_code == 204
        assert client.get("/api/v1/admin/posters").json()["count"] == 0
        client.post(f"/api/v1/posts/{post['id']}/comments", json={"body": "다시 봤어요"})
        assert client.delete(f"/api/v1/admin/posts/{post['id']}").status_code == 204
        assert client.get(f"/api/v1/posts/{post['id']}").status_code == 404
        assert client.get("/api/v1/admin/comments").json()["count"] == 0  # 글과 함께 댓글도 지움


def test_logs_record_requests_without_query_strings():
    admin_log.LOG_BUFFER.clear()
    ctx, client = make()
    with client:
        signup_admin(client, ctx)
        client.get("/api/v1/posts?species=dog&secret=abc")
        items = client.get("/api/v1/admin/logs?source=request").json()["items"]
        paths = [i["path"] for i in items]
        assert "/posts" in paths and not any("secret" in i["message"] for i in items)
        assert not any(p == "/admin/logs" for p in paths)
        warn = client.get("/api/v1/admin/logs?level=WARNING").json()["items"]
        assert all(i["level"] == "WARNING" for i in warn)


def test_list_kind_projects_fields(tmp_path):
    async def go():
        store = SqliteStore(str(tmp_path / "x.db"))
        await store.put("o1", "run", "1", {"status": "ok", "candidates": [1, 2]})
        rows = await store.list_kind("run", fields=("status",))
        await store.aclose()
        return rows

    rows = asyncio.run(go())
    assert rows[0]["owner"] == "o1" and rows[0]["data"] == {"status": "ok"}


def test_create_admin_script(tmp_path, monkeypatch):
    from scripts import create_admin

    store_path = str(tmp_path / "admin.db")
    monkeypatch.setattr(create_admin, "build_store", lambda settings: SqliteStore(store_path))
    monkeypatch.setenv("ADMIN_PASSWORD", "password123")
    asyncio.run(create_admin.main(ADMIN, "관리자", False))

    async def read():
        store = SqliteStore(store_path)
        account = await store.get(owner_key(ADMIN), "identity", "account")
        await store.aclose()
        return account

    account = asyncio.run(read())
    assert account["role"] == "admin" and account["password_hash"] != "password123"
    asyncio.run(create_admin.main(ADMIN, "관리자", False))  # 다시 실행해도 역할만 유지
    assert asyncio.run(read())["role"] == "admin"
