"""LangChain OpenAI 클라이언트 주입으로 특징 추출을 시험한다(실제 호출 아님)."""

import asyncio

import pytest

from backend.agent.llm import FeatureExtractor, LlmError


class FakeMessage:
    def __init__(self, finish_reason="stop"):
        self.response_metadata = {"finish_reason": finish_reason}


class FakeChatClient:
    def __init__(self, response=None, error=None, parsing_error=None, finish_reason="stop"):
        self.response = response
        self.error = error
        self.parsing_error = parsing_error
        self.finish_reason = finish_reason
        self.messages = None
        self.schema_options = None

    def with_structured_output(self, schema, **options):
        self.schema_options = (schema, options)
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        if self.error:
            raise self.error
        return {
            "raw": FakeMessage(self.finish_reason),
            "parsed": self.response,
            "parsing_error": self.parsing_error,
        }


def extractor(client):
    return FeatureExtractor("sk-test", "gpt-6-luna", client=client)


def test_extract_filters_ungrounded_values():
    client = FakeChatClient({"colors": ["갈색"], "breed": "시바견", "sex": "F", "marks": ["목줄"]})
    out = asyncio.run(extractor(client).extract("갈색 푸들, 빨간 목줄"))
    assert out.colors == ["갈색"]
    assert out.breed == ""  # 설명에 없는 품종은 버린다
    assert out.sex == "F" and out.marks == ["목줄"]
    assert client.messages[0][0] == "system" and client.messages[1][1] == "갈색 푸들, 빨간 목줄"
    assert client.schema_options[1] == {"method": "json_schema", "strict": True, "include_raw": True}


def test_photo_analysis_uses_injected_langchain_client():
    payload = {
        "animal_present": True,
        "identifiable": True,
        "center_subject_clear": True,
        "confidence": {
            key: 0.95
            for key in ("animal_present", "identifiable", "center_subject_clear", "species", "breed", "sex")
        },
        "species": "dog",
        "colors": [],
        "marks": [],
    }
    client = FakeChatClient(payload)
    result = asyncio.run(extractor(client).analyze_photo(b"image", "image/jpeg"))
    assert result.suitable and result.species == "dog"
    image_part = client.messages[1][1][1]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")


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
def test_client_errors_classified(status, body, code):
    class FakeApiError(Exception):
        def __init__(self):
            self.status_code = status
            self.body = body

    with pytest.raises(LlmError) as info:
        asyncio.run(extractor(FakeChatClient(error=FakeApiError())).extract("갈색"))
    assert info.value.code == code


def test_incomplete_or_bad_json_is_llm_response():
    with pytest.raises(LlmError) as info:
        asyncio.run(extractor(FakeChatClient(finish_reason="length")).extract("갈색"))
    assert info.value.code == "llm_response"


def test_input_and_structured_response_are_validated():
    client = FakeChatClient({"colors": ["보라"], "breed": "", "sex": "", "marks": []})
    with pytest.raises(LlmError, match="llm_response"):
        asyncio.run(extractor(client).extract("갈색"))
    with pytest.raises(LlmError, match="llm_request"):
        asyncio.run(extractor(client).extract("  "))
    with pytest.raises(LlmError, match="llm_request"):
        asyncio.run(extractor(client).analyze_photo(b"", "image/jpeg"))
    with pytest.raises(LlmError, match="llm_request"):
        asyncio.run(extractor(client).analyze_photo(b"image", "image/gif"))
    with pytest.raises(LlmError) as info:
        asyncio.run(extractor(FakeChatClient(parsing_error=ValueError("invalid structured response"))).extract("갈색"))
    assert info.value.code == "llm_response"


def test_timeout_classified():
    class APITimeoutError(TimeoutError):
        pass
    with pytest.raises(LlmError) as info:
        asyncio.run(extractor(FakeChatClient(error=APITimeoutError())).extract("갈색"))
    assert info.value.code == "llm_timeout"
