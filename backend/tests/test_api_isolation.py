"""검색 API·위치 API·사용자 격리. 카카오는 모의 transport 로 대체한다."""

from datetime import date, timedelta

import httpx
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.tools.kakao import KakaoGeocoder

from .conftest import ORIGIN, FakeAnimal, api_item, build_ctx, signup

START = (date.today() - timedelta(days=7)).isoformat()


def make_client(kakao_handler=None):
    kakao = KakaoGeocoder("test-key", transport=httpx.MockTransport(kakao_handler)) if kakao_handler else KakaoGeocoder(None)
    ctx = build_ctx(animal=FakeAnimal(pages=[[api_item(1), api_item(2)]]), kakao=kakao)
    return TestClient(create_app(ctx), headers={"Origin": ORIGIN}), ctx


def test_search_requires_login():
    client, _ = make_client()
    with client:
        assert client.post("/api/v1/searches", json={"criteria": {}}).status_code == 401


def test_runs_isolated_between_users():
    client, ctx = make_client()
    with client:
        signup(client, "a@example.com")
        run = client.post("/api/v1/searches", json={"criteria": {"species": "dog", "region": "전체", "lost_date": START}}).json()
        assert run["status"] == "completed"
        client.post("/api/v1/auth/logout")
        signup(client, "b@example.com")
        assert client.get(f"/api/v1/runs/{run['run_id']}").status_code == 404
        cid = run["candidates"][0]["id"]
        assert client.get(f"/api/v1/runs/{run['run_id']}/candidates/{cid}/location").status_code == 404
        assert client.get("/api/v1/runs").json()["runs"] == []


def test_location_success_cached_and_error_not_cached():
    phase = {"search": True}

    def handler(request):
        if phase["search"]:  # 검색 단계 상위 후보 조회는 실패시킨다
            return httpx.Response(500)
        return httpx.Response(200, json={"documents": [{"x": "126.84", "y": "37.55"}]})

    client, _ = make_client(handler)
    with client:
        signup(client)
        run = client.post("/api/v1/searches", json={"criteria": {"species": "dog", "region": "전체", "lost_date": START}}).json()
        cand = run["candidates"][0]
        assert cand["location"]["status"] == "error"  # 실패는 기록만, 캐시 아님
        phase["search"] = False
        url = f"/api/v1/runs/{run['run_id']}/candidates/{cand['id']}/location"
        first = client.get(url).json()
        assert first["status"] == "ok" and first["cached"] is False
        second = client.get(url).json()
        assert second["cached"] is True


def test_location_kakao_error_returns_502():
    def handler(request):
        return httpx.Response(401)

    client, _ = make_client(handler)
    with client:
        signup(client)
        run = client.post("/api/v1/searches", json={"criteria": {"species": "dog", "region": "전체", "lost_date": START}}).json()
        cid = run["candidates"][0]["id"]
        res = client.get(f"/api/v1/runs/{run['run_id']}/candidates/{cid}/location")
        assert res.status_code == 502 and res.json()["detail"]["code"] == "location_auth"


def test_kakao_reason_codes():
    import asyncio

    def handler(request):
        q = request.url.params["query"]
        if q == "none":
            return httpx.Response(200, json={"documents": []})
        if q == "many":
            return httpx.Response(200, json={"documents": [{"x": "127", "y": "37"}, {"x": "128", "y": "36"}]})
        return httpx.Response(200, json={"documents": [{"x": "0", "y": "0"}]})

    k = KakaoGeocoder("k", transport=httpx.MockTransport(handler))
    assert asyncio.run(k.geocode("none"))["reason"] == "address_not_found"
    assert asyncio.run(k.geocode("many"))["reason"] == "address_ambiguous"
    assert asyncio.run(k.geocode("zero"))["reason"] == "invalid_coordinates"
    assert asyncio.run(k.geocode(""))["reason"] == "address_missing"
    assert asyncio.run(KakaoGeocoder(None).geocode("서울"))["reason"] == "not_configured"


def test_notices_list_and_detail_cache(client):
    body = client.get("/api/v1/notices?species=dog").json()
    assert body["data_source"] == "sample" and body["items"]
    nid = body["items"][0]["id"]
    assert client.get(f"/api/v1/notices/{nid}").json()["id"] == nid
    missing = client.get("/api/v1/notices/does-not-exist")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "notice_not_cached"


def test_saved_search_and_memory_isolated(client):
    signup(client, "a@example.com")
    saved = client.post("/api/v1/saved-searches", json={"title": "초코", "criteria": {"species": "dog"}}).json()
    client.put("/api/v1/memory", json={"profile_id": "choco", "confirmed": {"color": "갈색", "region": "서울특별시"}})
    assert client.get("/api/v1/memory/choco").json()["confirmed"] == {"color": "갈색"}
    client.post("/api/v1/auth/logout")
    signup(client, "b@example.com")
    assert client.get("/api/v1/saved-searches").json()["saved_searches"] == []
    assert client.delete(f"/api/v1/saved-searches/{saved['key']}").status_code == 404
    assert client.get("/api/v1/memory/choco").status_code == 404
