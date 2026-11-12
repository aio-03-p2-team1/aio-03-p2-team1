"""OpenAI 기반 특징 추출 (live 모드).

LLM 은 보호자가 쓴 자유 서술에서 털색·품종·성별·특징 키워드만 구조화한다.
공고 번호·연락처·날짜·좌표는 절대 만들지 않는다(입력에도 넣지 않는다).
오류는 prompt.md 6.3 코드로 분류하고, 원본 메시지·응답 본문·키는 남기지 않는다.
"""

from __future__ import annotations

import json
import logging

import httpx

log = logging.getLogger("dasimanna.llm")

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
PROMPT_VERSION = "feature-extract-v1"
SYSTEM_PROMPT = (
    "너는 잃어버린 반려동물 설명에서 외형 특징만 추출하는 도우미다. "
    "설명에 없는 내용은 만들지 말고 빈 값으로 둔다. "
    'JSON 객체 하나만 출력한다: {"colors": [..], "breed": "", "sex": "M|F|", "marks": [..]}. '
    "colors 는 갈색·흰색·검정·회색·크림·노랑·주황·삼색·고등어 중에서만 고른다. "
    "marks 는 목줄·상처·중성화 같은 짧은 명사 키워드다."
)
ALLOWED_COLORS = {"갈색", "흰색", "검정", "회색", "크림", "노랑", "주황", "삼색", "고등어"}


class LlmError(RuntimeError):
    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


def classify(status: int, body: dict | None) -> str:
    err = (body or {}).get("error") or {}
    if status == 401:
        return "llm_auth"
    if status == 403:
        return "llm_permission"
    if status == 404:
        return "llm_model"
    if status == 429:
        return "llm_quota" if err.get("code") in {"insufficient_quota", "billing_hard_limit_reached"} else "llm_rate_limit"
    if 400 <= status < 500:
        return "llm_request"
    return "llm_upstream"


class FeatureExtractor:
    def __init__(self, api_key: str, model: str, timeout: float = 30, transport=None):
        self._key = api_key
        self.model = model
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def extract(self, description: str) -> dict:
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": description[:1000]},
            ],
        }
        try:
            res = await self._client.post(OPENAI_URL, json=payload, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.TimeoutException as exc:
            raise LlmError("llm_timeout") from exc
        except httpx.HTTPError as exc:
            raise LlmError("llm_network") from exc
        request_id = res.headers.get("x-request-id")
        if res.status_code >= 400:
            try:
                body = res.json()
            except ValueError:
                body = None
            code = classify(res.status_code, body)
            log.warning("openai error status=%s code=%s request_id=%s", res.status_code, code, request_id)
            raise LlmError(code, res.status_code)
        try:
            choice = res.json()["choices"][0]
            if choice.get("finish_reason") not in (None, "stop"):
                raise LlmError("llm_response", res.status_code)
            data = json.loads(choice["message"]["content"])
        except LlmError:
            raise
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LlmError("llm_response", res.status_code) from exc
        if not isinstance(data, dict):
            raise LlmError("llm_response", res.status_code)
        colors = [c for c in data.get("colors") or [] if c in ALLOWED_COLORS]
        sex = data.get("sex") if data.get("sex") in ("M", "F") else ""
        marks = [str(m)[:20] for m in (data.get("marks") or []) if isinstance(m, str) and m.strip()][:6]
        breed = str(data.get("breed") or "")[:30]
        # 설명에 실제로 등장하지 않는 품종은 버린다(근거 없는 특징 생성 방지).
        if breed and breed.replace(" ", "") not in description.replace(" ", ""):
            breed = ""
        return {"colors": colors, "breed": breed, "sex": sex, "marks": marks, "model": self.model, "prompt_version": PROMPT_VERSION}
