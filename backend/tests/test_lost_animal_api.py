"""분실동물 조회 API 도구 시험. 실제 호출 없이 httpx 모의 transport 로만 확인한다."""

import asyncio
from datetime import date

import httpx
import pytest

from backend.tools.lost_animal_api import LostAnimalApi, LostAnimalApiError

from .conftest import make_settings


def run(coro):
    return asyncio.run(coro)


def client(handler, key="test-key"):
    return LostAnimalApi("https://example.test/lossInfoService", key, transport=httpx.MockTransport(handler))


def ok_body(items, total=None):
    """공공데이터포털 JSON 응답 형태. items 는 1건이면 dict, 여러 건이면 list 로 오는 실제 형태를 흉내 낸다."""
    item = items[0] if len(items) == 1 else items
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {"items": {"item": item} if items else "", "totalCount": total if total is not None else len(items),
                     "pageNo": 1, "numOfRows": 100},
        }
    }


def test_search_sends_official_parameters():
    seen = {}

    def handler(request: httpx.Request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=ok_body([{"a": 1}, {"a": 2}], total=57))

    page = run(client(handler).search(start=date(2026, 11, 1), end=date(2026, 11, 14), species="cat",
                                      region_code="6110000", sex="F", rows=2))
    assert seen["path"].endswith("/lossInfo")
    params = seen["params"]
    assert params["bgnde"] == "20261101" and params["ended"] == "20261114"
    assert params["upkind"] == "422400" and params["upr_cd"] == "6110000" and params["sex_cd"] == "F"
    assert params["_type"] == "json" and params["numOfRows"] == "2" and params["serviceKey"] == "test-key"
    assert "org_cd" not in params  # 값이 없는 선택 변수는 보내지 않는다
    assert page.total_count == 57 and len(page.items) == 2


def test_single_item_and_empty_result_are_lists():
    one = run(client(lambda r: httpx.Response(200, json=ok_body([{"a": 1}]))).search(
        start=date(2026, 11, 1), end=date(2026, 11, 2)))
    assert one.items == [{"a": 1}]
    empty = run(client(lambda r: httpx.Response(200, json=ok_body([]))).search(
        start=date(2026, 11, 1), end=date(2026, 11, 2)))
    assert empty.items == [] and empty.total_count == 0  # 0건은 오류가 아니다


def test_encoded_key_is_decoded_once():
    seen = {}

    def handler(request: httpx.Request):
        seen["key"] = request.url.params["serviceKey"]
        return httpx.Response(200, json=ok_body([]))

    run(client(handler, key="abc%2Bdef%3D%3D").search(start=date(2026, 11, 1), end=date(2026, 11, 2)))
    assert seen["key"] == "abc+def=="


@pytest.mark.parametrize(
    "response, code",
    [
        (httpx.Response(200, text="<OpenAPI_ServiceResponse>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</OpenAPI_ServiceResponse>"), "lost_auth"),
        (httpx.Response(200, text="LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"), "lost_rate_limit"),
        (httpx.Response(502, text="bad gateway"), "lost_upstream"),
        (httpx.Response(200, json={"response": {"header": {"resultCode": "99", "resultMsg": "ERR"}}}), "lost_response"),
        (httpx.Response(200, text="not json"), "lost_response"),
    ],
)
def test_failures_raise_instead_of_empty(response, code):
    with pytest.raises(LostAnimalApiError) as exc:
        run(client(lambda r: response).search(start=date(2026, 11, 1), end=date(2026, 11, 2)))
    assert exc.value.code == code


def test_network_error_is_reported():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(LostAnimalApiError) as exc:
        run(client(handler).search(start=date(2026, 11, 1), end=date(2026, 11, 2)))
    assert exc.value.code == "lost_network"


def test_settings_reads_lost_key_and_forces_https():
    settings = make_settings(lost_animal_api_key=" ", lost_animal_api_base_url="http://apis.data.go.kr/1543061/lossInfoService/")
    assert settings.lost_animal_api_key is None  # 빈 값은 '없음'으로 본다
    assert settings.lost_animal_api_base_url == "https://apis.data.go.kr/1543061/lossInfoService"
