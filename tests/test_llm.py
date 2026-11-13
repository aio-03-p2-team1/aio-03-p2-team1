"""OpenAI 특징 추출: 모의 transport 로만 시험한다(실제 OpenAI 호출 아님)."""

import asyncio
import json

import httpx
import pytest

from backend.agent.llm import FeatureExtractor, LlmError


def extractor(handler):
    return FeatureExtractor("sk-test", "gpt-6-luna", transport=httpx.MockTransport(handler))


def reply(content: dict, finish="stop"):
    return httpx.Response(200, json={"choices": [{"finish_reason": finish, "message": {"content": json.dumps(content, ensure_ascii=False)}}]})


def test_extract_filters_ungrounded_values():
    def handler(request):
        return reply({"colors": ["갈색", "보라"], "breed": "시바견", "sex": "F", "marks": ["목줄"]})

    out = asyncio.run(extractor(handler).extract("갈색 푸들, 빨간 목줄"))
    assert out["colors"] == ["갈색"]
    assert out["breed"] == ""  # 설명에 없는 품종은 버린다
    assert out["sex"] == "F" and out["marks"] == ["목줄"]


@pytest.mark.parametrize(
    "status,body,code",
    [
        (401, {}, "llm_auth"),
        (403, {}, "llm_permission"),
        (404, {}, "llm_model"),
        (429, {"error": {"code": "insufficient_quota"}}, "llm_quota"),
        (429, {"error": {"code": "rate_limit_exceeded"}}, "llm_rate_limit"),
        (400, {}, "llm_request"),
        (503, {}, "llm_upstream"),
    ],
)
def test_http_errors_classified(status, body, code):
    with pytest.raises(LlmError) as info:
        asyncio.run(extractor(lambda r: httpx.Response(status, json=body)).extract("갈색"))
    assert info.value.code == code


def test_incomplete_or_bad_json_is_llm_response():
    with pytest.raises(LlmError) as info:
        asyncio.run(extractor(lambda r: reply({}, finish="length")).extract("갈색"))
    assert info.value.code == "llm_response"
    bad = httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]})
    with pytest.raises(LlmError) as info:
        asyncio.run(extractor(lambda r: bad).extract("갈색"))
    assert info.value.code == "llm_response"


def test_timeout_classified():
    def handler(request):
        raise httpx.ConnectTimeout("t", request=request)

    with pytest.raises(LlmError) as info:
        asyncio.run(extractor(handler).extract("갈색"))
    assert info.value.code == "llm_timeout"
