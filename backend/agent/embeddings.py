import math
import httpx
from langchain_openai import OpenAIEmbeddings

from backend.agent.llm import LlmError, classify

MODEL = "text-embedding-3-small"
DIMENSIONS = 1536


class Embedder:
    model = MODEL

    def __init__(self, key, timeout=60, transport=None, client=None):
        http_client = httpx.AsyncClient(timeout=timeout, transport=transport) if transport is not None else None
        self.client = client or OpenAIEmbeddings(
            model=MODEL,
            dimensions=DIMENSIONS,
            api_key=key,
            request_timeout=timeout,
            max_retries=0,
            http_async_client=http_client,
        )

    async def embed(self, texts):
        vectors = []
        for start in range(0, len(texts), 128):
            batch = texts[start:start + 128]
            try:
                batch_vectors = await self.client.aembed_documents(batch)
                if len(batch_vectors) != len(batch):
                    raise ValueError("count")
                for vector in batch_vectors:
                    if len(vector) != DIMENSIONS or any(
                        not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in vector
                    ) or not any(vector):
                        raise ValueError("vector")
                    vectors.append(vector)
            except LlmError:
                raise
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                body = getattr(exc, "body", None)
                if status:
                    raise LlmError(classify(status, body if isinstance(body, dict) else None), status) from exc
                name = type(exc).__name__.lower()
                if isinstance(exc, (httpx.TimeoutException, TimeoutError)) or "timeout" in name:
                    raise LlmError("llm_timeout") from exc
                if isinstance(exc, httpx.HTTPError) or "connection" in name:
                    raise LlmError("llm_network") from exc
                if isinstance(exc, (ValueError, KeyError, TypeError)):
                    raise LlmError("llm_response") from exc
                raise LlmError("llm_upstream") from exc
        return vectors
