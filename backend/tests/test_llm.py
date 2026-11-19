"""LangChain OpenAI 클라이언트 주입으로 특징 추출을 시험한다(실제 호출 아님)."""

import asyncio

import pytest

from backend.agent.llm import (
    COLOR_VALUES_TEXT,
    ORGANIZED_TEXT_MESSAGE,
    PHOTO_ONLY_MESSAGE,
    INPUT_REVIEW_PROMPT_VERSION,
    PHOTO_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    FeatureExtractor,
    LlmError,
)
from backend.schemas.api import PhotoAnalysisResponse
from backend.schemas.llm import PhotoAnalysisModelResponse, PhotoAnalysisResult


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
    client = FakeChatClient({"colors": ["갈색", "흰색", "갈색"], "sex": "F", "marks": ["목줄"]})
    out = asyncio.run(extractor(client).extract("갈색과 흰색 푸들, 빨간 목줄"))
    assert out.colors == ["갈색", "흰색"]
    assert "breed" not in out.model_dump()
    assert out.sex == "F" and out.marks == ["목줄"]
    assert client.messages[0][0] == "system" and client.messages[1][1] == "갈색과 흰색 푸들, 빨간 목줄"
    assert COLOR_VALUES_TEXT in client.messages[0][1]
    assert client.schema_options[1] == {"method": "json_schema", "strict": True, "include_raw": True}


def test_photo_analysis_uses_injected_langchain_client():
    payload = {
        "animal_present": True,
        "identifiable": True,
        "center_subject_clear": True,
        "confidence": {
            key: 0.95
            for key in ("animal_present", "identifiable", "center_subject_clear", "species", "breed_code", "sex")
        },
        "species": "dog",
        "breed_code": "",
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
    image_part = client.messages[1][1][1]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")


def review_payload(**overrides):
    payload = {
        "fur_color": "흰색", "features": "빨간 목줄, 짧은 꼬리", "situation": "11월 12일 수원 정자동에서 실종", "other": "",
        "colors": ["흰색", "갈색"], "sex": "F", "marks": ["빨간 목줄", "빨간 목줄", "짧은 꼬리"],
        "duplicates": ["흰색(글과 사진)"],
        "conflicts": [{"item": "털색", "text_value": "흰색", "photo_value": "갈색"}],
        "action": "search", "question": "", "message": "흰색은 글과 사진에 겹쳐 하나로 합쳤고, 털색은 글 기준으로 찾을게요.",
        "breed_mention": "푸들", "animal_kind": "",
    }
    payload.update(overrides)
    return payload


def test_review_input_merges_text_and_photo_features_in_one_call():
    client = FakeChatClient(review_payload())
    photo = {"suitable": True, "species": "dog", "breed": "", "colors": ["갈색"], "sex": "", "marks": ["짧은 꼬리"]}
    result = asyncio.run(extractor(client).review_input("사진에서 확인한 특징: 갈색\n흰색 암컷, 빨간 목줄", photo, "dog"))
    assert result.organized_text == "[털색]: 흰색\n[특징]: 빨간 목줄, 짧은 꼬리\n[상황]: 11월 12일 수원 정자동에서 실종"
    assert result.features == {"colors": ["흰색", "갈색"], "sex": "F", "marks": ["빨간 목줄", "짧은 꼬리"]}
    assert result.duplicates == ["흰색(글과 사진)"]
    assert result.conflicts == [{"item": "털색", "text_value": "흰색", "photo_value": "갈색"}]
    assert result.action == "search" and result.question == ""
    assert result.breed_mention == "푸들" and result.animal_kind == ""
    assert result.prompt_version == INPUT_REVIEW_PROMPT_VERSION
    # 사진은 다시 보내지 않고, 서버가 보관한 사진 분석 특징을 글과 함께 한 번에 보낸다.
    human = client.messages[1][1]
    assert isinstance(human, str) and "[사용자 글]" in human and "[사진 분석 특징]" in human and "짧은 꼬리" in human
    assert "[찾는 동물 종류]\n강아지" in human


def test_review_input_without_question_does_not_stop_to_ask():
    client = FakeChatClient(review_payload(action="ask", question="  "))
    result = asyncio.run(extractor(client).review_input("갈색 강아지", None))
    assert result.action == "search" and result.question == ""


def test_review_input_keeps_breed_only_for_dogs_and_cats_and_kind_only_for_etc():
    client = FakeChatClient(review_payload(breed_mention="푸들", animal_kind="새"))
    etc = asyncio.run(extractor(client).review_input("초록색 앵무새", None, "etc"))
    assert etc.breed_mention == "" and etc.animal_kind == "새"
    dog = asyncio.run(extractor(FakeChatClient(review_payload(animal_kind="새"))).review_input("푸들", None, "dog"))
    assert dog.breed_mention == "푸들" and dog.animal_kind == ""


def test_classify_animal_photos_sends_all_photos_in_one_call():
    client = FakeChatClient({"labels": [{"index": 1, "kind": "소"}, {"index": 0, "kind": "새"}, {"index": 9, "kind": "새"}]})
    labels = asyncio.run(extractor(client).classify_animal_photos([(b"a", "image/jpeg"), (b"b", "image/png"), (b"c", "image/jpeg")]))
    assert labels == ["새", "소", "모름"]  # 빠진 번호는 모름, 범위 밖 번호는 무시
    images = [part for part in client.messages[1][1] if part["type"] == "image_url"]
    assert len(images) == 3 and all(part["image_url"]["detail"] == "low" for part in images)


def test_review_input_uses_previous_review_memory_of_the_same_thread():
    """모델은 이전 호출을 기억하지 못하므로 서버가 넘긴 직전 검토 기억으로 판단한다."""
    organized = "[털색]: 흰색, 회색\n[특징]: 이마와 얼굴의 회색 줄무늬\n[상황]: 마지막으로 본 곳 공원"
    previous = {"organized_text": organized, "duplicates": ["흰색·회색 털색"], "conflicts": [], "confirmed_items": []}
    client = FakeChatClient(review_payload(conflicts=[], duplicates=["흰색·회색 털색"], message="흰색이 반복되어 합쳤습니다."))
    photo = {"suitable": True, "species": "cat", "breed": "", "colors": ["흰색", "회색"], "sex": "", "marks": []}
    result = asyncio.run(extractor(client).review_input(organized, photo, "cat", previous=previous))
    assert result.duplicates == []  # 자기가 정리한 글 그대로면 새 중복이 아니다
    assert result.message == ORGANIZED_TEXT_MESSAGE
    human = client.messages[1][1]
    assert "[이전 검토(같은 대화)]" in human and '"지금_글이_이전에_정리한_글과_같음": true' in human


def test_review_input_does_not_ask_again_about_items_the_user_confirmed():
    previous = {"organized_text": "[털색]: 기타", "duplicates": ["목 깃털 무늬"], "conflicts": [], "confirmed_items": ["털색"]}
    client = FakeChatClient(review_payload(
        action="ask", question="털색이 맞나요?", duplicates=["목 깃털 무늬", "빨간 목줄"],
        conflicts=[{"item": "털색", "text_value": "기타", "photo_value": "회색"}]))
    result = asyncio.run(extractor(client).review_input("[털색]: 기타: 회색\n[특징]: 빨간 목줄", None, "etc", previous=previous))
    assert result.conflicts == [] and result.action == "search" and result.question == ""
    assert result.duplicates == ["빨간 목줄"]  # 이미 보고한 중복은 다시 올리지 않는다


def test_review_input_with_photo_only_reports_no_duplicates():
    """사진만 올리면 화면이 넣은 '사진에서 확인한 특징' 줄은 사진 특징과 같은 출처라 중복으로 보지 않는다."""
    client = FakeChatClient(review_payload(conflicts=[], duplicates=["흰색", "회색", "고등어무늬"], message="중복을 합쳤습니다."))
    photo = {"suitable": True, "species": "cat", "breed": "", "colors": ["흰색", "회색"], "sex": "", "marks": ["고등어무늬"]}
    result = asyncio.run(extractor(client).review_input("사진에서 확인한 특징: 흰색, 회색, 고등어무늬", photo, "cat"))
    assert result.duplicates == [] and result.message == PHOTO_ONLY_MESSAGE
    assert "사진에서 확인한 특징" not in client.messages[1][1].split("[사진 분석 특징]")[0]


def test_review_input_rejects_empty_input_without_calling_model():
    client = FakeChatClient(review_payload())
    with pytest.raises(LlmError) as exc:
        asyncio.run(extractor(client).review_input("  ", {"suitable": False}))
    assert exc.value.code == "llm_request" and client.messages is None


def test_color_value_template_is_rendered_into_both_prompts():
    assert COLOR_VALUES_TEXT in SYSTEM_PROMPT
    assert COLOR_VALUES_TEXT in PHOTO_SYSTEM_PROMPT
    assert "message" not in PhotoAnalysisModelResponse.model_fields
    assert "message" not in PhotoAnalysisResult.model_fields
    assert "reason_code" in PhotoAnalysisResult.model_fields
    assert "reason_code" in PhotoAnalysisResponse.model_fields
    assert "message" not in PhotoAnalysisResponse.model_fields
    assert "model" not in PhotoAnalysisResult.model_fields
    assert "prompt_version" not in PhotoAnalysisResult.model_fields
    assert "model" not in PhotoAnalysisResponse.model_fields
    assert "prompt_version" not in PhotoAnalysisResponse.model_fields


def test_photo_reason_code_is_derived_from_suitability_reason():
    payload = {
        "animal_present": True,
        "identifiable": True,
        "center_subject_clear": False,
        "confidence": {
            "animal_present": 0.95,
            "identifiable": 0.95,
            "center_subject_clear": 0.5,
            "species": 0.95,
            "breed_code": 0.95,
            "sex": 0.95,
        },
        "species": "dog",
        "breed_code": "",
        "sex": "",
        "colors": [],
        "marks": [],
    }
    result = asyncio.run(extractor(FakeChatClient(payload)).analyze_photo(b"image", "image/jpeg"))

    assert not result.suitable
    assert result.reason_code == "subject_not_distinct"


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
    client = FakeChatClient({"colors": ["자주색"], "sex": "", "marks": []})
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


@pytest.mark.parametrize("code,expected", [("1", "푸들"), ("unknown", ""), ("", "")])
def test_photo_uses_cached_codes_and_rejects_unknown_code(code, expected):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    payload = {
        'animal_present': True, 'identifiable': True, 'center_subject_clear': True,
        'confidence': {key: .95 for key in ('animal_present', 'identifiable', 'center_subject_clear', 'species', 'breed_code', 'sex')},
        'species': 'dog', 'breed_code': code, 'sex': '', 'colors': [], 'marks': [],
    }
    client = FakeChatClient(payload)
    model = extractor(client)
    model.kinds = SimpleNamespace(catalog=AsyncMock(return_value=(("1", "푸들"), ("2", "코리안 숏헤어"))))
    result = asyncio.run(model.analyze_photo(b'image', 'image/jpeg'))
    assert result.breed == expected
    assert result.breed_code == (code if expected else '')
    prefix = client.messages[0][1]
    assert '["1", "푸들"]' in prefix


def test_photo_empty_catalog_does_not_accept_generated_code():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    payload = {
        'animal_present': True, 'identifiable': True, 'center_subject_clear': True,
        'confidence': {key: .95 for key in ('animal_present', 'identifiable', 'center_subject_clear', 'species', 'breed_code', 'sex')},
        'species': 'dog', 'breed_code': '1', 'sex': '', 'colors': [], 'marks': [],
    }
    model = extractor(FakeChatClient(payload))
    model.kinds = SimpleNamespace(catalog=AsyncMock(return_value=()))
    result = asyncio.run(model.analyze_photo(b'image', 'image/jpeg'))
    assert result.breed_code == result.breed == ''


def test_prompt_cache_key_reaches_openai_request_transport():
    import json
    import httpx
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={
            'id': 'mock-completion', 'object': 'chat.completion', 'created': 0, 'model': 'gpt-6-luna',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': json.dumps({'colors': [], 'sex': '', 'marks': []})}}],
            'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
        })

    async def invoke():
        model = FeatureExtractor('test-only', 'gpt-6-luna', transport=httpx.MockTransport(handler))
        try:
            await model.extract('목줄')
        finally:
            await model.aclose()

    asyncio.run(invoke())
    assert requests[0]['prompt_cache_key'] == 'dasimanna-features-photo-v8'
    properties = requests[0]['response_format']['json_schema']['schema']['properties']
    assert 'breed' not in properties


def test_feature_prompt_version_is_current():
    from backend.agent.llm import PROMPT_VERSION
    assert PROMPT_VERSION == 'feature-extract-v8'
