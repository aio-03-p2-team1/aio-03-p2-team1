"""LangChain OpenAI 클라이언트 주입으로 특징 추출을 시험한다(실제 호출 아님)."""

import asyncio

import pytest

from backend.agent.llm import (
    COLOR_VALUES_TEXT,
    PHOTO_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    FeatureExtractor,
    LlmError,
)
from backend.agent.schema import PhotoAnalysisModelResponse, PhotoAnalysisResponse


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


def test_extract_keeps_multiple_colors_and_filters_duplicates():
    client = FakeChatClient({"colors": ["갈색", "흰색", "갈색"], "breed": "시바견", "sex": "F", "marks": ["목줄"]})
    out = asyncio.run(extractor(client).extract("갈색과 흰색 푸들, 빨간 목줄"))
    assert out.colors == ["갈색", "흰색"]
    assert out.breed == ""  # 설명에 없는 품종은 버린다
    assert out.sex == "F" and out.marks == ["목줄"]
    assert client.messages[0][0] == "system" and client.messages[1][1] == "갈색과 흰색 푸들, 빨간 목줄"
    assert COLOR_VALUES_TEXT in client.messages[0][1]
    assert "각 색상을 모두 한 번씩 반환한다" in client.messages[0][1]
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
        "breed": "",
        "sex": "",
        "colors": [
            {"value": "갈색", "confidence": 0.95},
            {"value": "흰색", "confidence": 0.93},
            {"value": "갈색", "confidence": 0.95},
        ],
        "marks": [],
    }
    client = FakeChatClient(payload)
    result = asyncio.run(extractor(client).analyze_photo(b"image", "image/jpeg"))
    assert result.suitable and result.species == "dog"
    assert result.colors == ["갈색", "흰색"]
    assert COLOR_VALUES_TEXT in client.messages[0][1]
    assert "각 색상을 모두 별도 항목으로 반환하고" in client.messages[0][1]
    image_part = client.messages[1][1][1]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_color_value_template_is_rendered_into_both_prompts():
    assert COLOR_VALUES_TEXT in SYSTEM_PROMPT
    assert COLOR_VALUES_TEXT in PHOTO_SYSTEM_PROMPT
    assert "message" not in PHOTO_SYSTEM_PROMPT
    assert "message" not in PhotoAnalysisModelResponse.model_fields
    assert "message" in PhotoAnalysisResponse.model_fields


def test_photo_message_is_derived_from_suitability_reason():
    payload = {
        "animal_present": True,
        "identifiable": True,
        "center_subject_clear": False,
        "confidence": {
            "animal_present": 0.95,
            "identifiable": 0.95,
            "center_subject_clear": 0.5,
            "species": 0.95,
            "breed": 0.95,
            "sex": 0.95,
        },
        "species": "dog",
        "breed": "",
        "sex": "",
        "colors": [],
        "marks": [],
    }
    result = asyncio.run(extractor(FakeChatClient(payload)).analyze_photo(b"image", "image/jpeg"))

    assert not result.suitable
    assert result.message == "찾을 동물이 중심에서 구분되지 않아요. 동물이 중심에 보이는 사진을 올려 주세요."


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
