"""구조동물 API 도구: 모의 transport 로만 시험한다(실제 호출 아님)."""

import asyncio
from datetime import date

import httpx
import pytest

from backend.tools.animal_api import AnimalApi, AnimalApiError, SampleAnimalApi

from .conftest import api_item

BASE = "https://apis.data.go.kr/1543061/abandonmentPublicService_v2"


def run(coro):
    return asyncio.run(coro)


def api(handler, key="plain-key"):
    return AnimalApi(BASE, key, transport=httpx.MockTransport(handler))


def ok_body(items, total=None):
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {"items": {"item": items} if items else "", "totalCount": total if total is not None else len(items)},
        }
    }


def test_search_builds_params_and_normalizes():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(dict(request.url.params))
        assert request.url.path.endswith("/abandonmentPublic_v2")
        return httpx.Response(200, json=ok_body([api_item(1)], total=1))

    page = run(api(handler).search(region_code="6110000", start=date(2026, 11, 1), end=date(2026, 11, 12), species="dog"))
    assert seen["bgnde"] == "20261101" and seen["endde"] == "20261112"
    assert seen["upkind"] == "417000" and seen["upr_cd"] == "6110000" and seen["_type"] == "json"
    item = page.items[0]
    assert item["species"] == "dog" and item["care"]["tel"] == "02-000-0000"
    assert item["photos"][0].startswith("https://")
    assert page.source == "api" and page.total_count == 1


def test_all_species_omits_upkind():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=ok_body([]))

    page = run(api(handler).search(region_code=None, start=date(2026, 11, 1), end=date(2026, 11, 2), species="all"))
    assert "upkind" not in seen and "upr_cd" not in seen
    assert page.items == [] and page.total_count == 0  # 빈 결과는 오류가 아니다


def test_single_item_dict_is_accepted():
    def handler(request):
        body = ok_body([])
        body["response"]["body"]["items"] = {"item": api_item(2)}
        body["response"]["body"]["totalCount"] = 1
        return httpx.Response(200, json=body)

    page = run(api(handler).search(region_code=None, start=date(2026, 11, 1), end=date(2026, 11, 2), species="dog"))
    assert len(page.items) == 1


def test_encoded_key_is_decoded_once():
    seen = {}

    def handler(request):
        seen["raw"] = str(request.url)
        return httpx.Response(200, json=ok_body([]))

    run(api(handler, key="abc%2Bdef%3D%3D").search(region_code=None, start=date(2026, 11, 1), end=date(2026, 11, 2), species="dog"))
    assert "abc%2Bdef%3D%3D" in seen["raw"]  # 이중 인코딩(%252B)이 아니어야 한다


@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(200, text="<OpenAPI_ServiceResponse><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30</returnReasonCode></OpenAPI_ServiceResponse>"), "animal_auth"),
        (httpx.Response(403, text="Forbidden"), "animal_auth"),
        (httpx.Response(200, json={"response": {"header": {"resultCode": "22"}}}), "animal_rate_limit"),
        (httpx.Response(500, text="oops"), "animal_upstream"),
        (httpx.Response(200, text="not json"), "animal_response"),
    ],
)
def test_errors_are_classified_not_hidden(response, code):
    with pytest.raises(AnimalApiError) as info:
        run(api(lambda r: response).search(region_code=None, start=date(2026, 11, 1), end=date(2026, 11, 2), species="dog"))
    assert info.value.code == code


def test_timeout_is_retryable():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(AnimalApiError) as info:
        run(api(handler).search(region_code=None, start=date(2026, 11, 1), end=date(2026, 11, 2), species="dog"))
    assert info.value.code == "animal_timeout" and info.value.retryable


def test_regions_parsed():
    def handler(request):
        assert request.url.path.endswith("/sido_v2")
        return httpx.Response(200, json=ok_body([{"orgCd": "6110000", "orgdownNm": "서울특별시"}]))

    regions = run(api(handler).regions())
    assert regions[0].code == "6110000" and regions[0].name == "서울특별시"


def test_sample_source_is_labelled_and_filtered():
    sample = SampleAnimalApi()
    page = run(sample.search(region_code=None, start=date(2000, 1, 1), end=date.today(), species="cat"))
    assert page.source == "sample"
    assert page.items and all(i["species"] == "cat" and i["source"] == "sample" for i in page.items)
    assert all(i["id"].startswith("SAMPLE-") and i["care"]["tel"] is None for i in page.items)
