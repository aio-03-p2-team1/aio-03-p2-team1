"""테스트 공용 픽스처. 외부 API 는 모두 모의 transport·가짜 객체로 대체한다(실제 호출 없음)."""

from __future__ import annotations

from datetime import date, timedelta

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient

from backend.auth.sessions import SessionStore
from backend.config import Settings
from backend.deps import AppContext
from backend.main import create_app
from backend.storage.sqlite import SqliteStore
from backend.tools.animal_api import AnimalApiError, Region, SampleAnimalApi, SearchPage, normalize_item
from backend.tools.kakao import KakaoGeocoder

ORIGIN = "http://127.0.0.1:5173"


def make_settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        app_mode="local",
        storage_backend="sqlite",
        sqlite_path=":memory:",
        cors_origins="http://localhost:5173,http://127.0.0.1:5173",
        redis_url="redis://127.0.0.1:6380/0",
    )
    base.update(overrides)
    return Settings(**base)


def api_item(n: int, **fields) -> dict:
    """구조동물 API 형식의 원본 항목(모의 응답용)."""
    raw = {
        "desertionNo": f"4480000{n:05d}",
        "noticeNo": f"서울-강서-2026-{n:05d}",
        "upKindCd": "417000",
        "upKindNm": "개",
        "kindNm": "푸들",
        "sexCd": "F",
        "colorCd": "갈색",
        "happenDt": (date.today() - timedelta(days=2)).strftime("%Y%m%d"),
        "happenPlace": "강서구 공원",
        "specialMark": "회색 목줄 착용, 곱슬털",
        "processState": "보호중",
        "popfile1": "http://openapi.animal.go.kr/openapi/service/rest/fileDownloadSrv/img.jpg",
        "careNm": "강서 동물보호센터",
        "careTel": "02-000-0000",
        "careAddr": "서울특별시 강서구 테스트로 1",
        "orgNm": "서울특별시 강서구",
    }
    raw.update(fields)
    return raw


class FakeAnimal:
    """페이지별 응답·오류를 순서대로 돌려주는 가짜 구조동물 도구."""

    source = "api"

    def __init__(self, pages=None, regions=None, errors=None):
        self.pages = pages or [[]]
        self.errors = list(errors or [])
        self.region_list = regions or [Region("6110000", "서울특별시"), Region("6410000", "경기도")]
        self.calls: list[dict] = []
        self.region_calls = 0

    async def regions(self):
        self.region_calls += 1
        return self.region_list

    async def search(self, *, region_code, start, end, species, page=1, rows=50):
        self.calls.append({"region_code": region_code, "page": page, "species": species, "rows": rows})
        if self.errors:
            err = self.errors.pop(0)
            if err:
                raise AnimalApiError(err)
        all_rows = [raw for chunk in self.pages for raw in chunk]
        raws = all_rows[(page - 1) * rows:page * rows]
        total = sum(len(p) for p in self.pages)
        items = [normalize_item(r, "2026-11-12T00:00:00+00:00") for r in raws]
        return SearchPage(items=items, total_count=total, page=page, rows=rows, fetched_at="2026-11-12T00:00:00+00:00", source="api")


def kakao_transport(handler):
    return httpx.MockTransport(handler)


def build_ctx(settings=None, animal=None, kakao=None, llm=None, redis=None) -> AppContext:
    settings = settings or make_settings()
    return AppContext(
        settings=settings,
        store=SqliteStore(":memory:"),
        sessions=SessionStore(redis or fakeredis.FakeAsyncRedis(), settings.auth_session_ttl_seconds),
        animal=animal or SampleAnimalApi(),
        kakao=kakao or KakaoGeocoder(None),
        llm=llm,
        embedder=FakeEmbedder(),
    )


class FakeEmbedder:
    model = "fake-embedding"

    def __init__(self):
        self.calls = []

    async def embed(self, texts):
        self.calls.append(texts)
        return [[1.0, 0.0] for _ in texts]


@pytest.fixture
def ctx():
    return build_ctx()


@pytest.fixture
def client(ctx):
    with TestClient(create_app(ctx), headers={"Origin": ORIGIN}) as c:
        yield c


def signup(client, email="bori@example.com", name="보리 보호자", password="password123"):
    res = client.post("/api/v1/auth/register", json={"name": name, "email": email, "password": password})
    assert res.status_code == 201, res.text
    return res
