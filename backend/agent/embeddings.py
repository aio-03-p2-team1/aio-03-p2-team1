import math
import httpx

from backend.agent.llm import LlmError, classify

MODEL = "text-embedding-3-small"
DIMENSIONS = 1536


class Embedder:
    model = MODEL

    def __init__(self, key, timeout=60, transport=None):
        self.key = key
        self.client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def embed(self, texts):
        vectors = []
        for start in range(0, len(texts), 128):
            batch = texts[start:start + 128]
            try:
                res = await self.client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.key}"},
                    json={"model": MODEL, "input": batch, "dimensions": DIMENSIONS},
                )
            except httpx.TimeoutException as exc:
                raise LlmError("llm_timeout") from exc
            except httpx.HTTPError as exc:
                raise LlmError("llm_network") from exc
            try:
                body = res.json()
                if not isinstance(body, dict):
                    raise ValueError("response")
                if res.status_code >= 400:
                    raise LlmError(classify(res.status_code, body), res.status_code)
                data = sorted(body["data"], key=lambda row: row["index"])
                if [row["index"] for row in data] != list(range(len(batch))):
                    raise ValueError("indices")
                for row in data:
                    vector = row["embedding"]
                    if len(vector) != DIMENSIONS or any(
                        not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in vector
                    ) or not any(vector):
                        raise ValueError("vector")
                    vectors.append(vector)
            except (ValueError, KeyError, TypeError) as exc:
                raise LlmError("llm_response") from exc
        return vectors
