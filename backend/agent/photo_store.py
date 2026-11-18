"""사진 분석 결과를 서버에 잠시 보관하고, 검색 때 번호(analysis_id)로 꺼낸다.

왜: 예전에는 화면이 설명 글 앞에 '사진에서 확인한 특징: …' 줄을 붙이고, 에이전트가 그 문장으로 사진을 받았는지
판단했다. 사용자가 그 줄을 지우거나 고치면 판단이 틀어지고(사진을 또 요청), 분석 실패도 구분할 수 없었다.
이제는 서버가 직접 분석한 결과만 믿는다. 설명 글의 사진 줄은 사용자에게 보여 주는 용도일 뿐이다.

- 키에 로그인 사용자(owner)를 넣어, 다른 사람의 번호로는 읽을 수 없다(사용자 격리).
- 저장하는 값은 분석 결과의 특징뿐이다(사진 자체는 저장하지 않는다). 1시간 뒤 사라진다.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

PHOTO_TTL_SECONDS = 3600
FIELDS = ("suitable", "species", "breed", "breed_code", "colors", "sex", "marks", "reason_code")
ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _key(owner: str, analysis_id: str) -> str:
    return f"photo-analysis:{owner}:{analysis_id}"


async def save(redis, owner: str, result: dict[str, Any]) -> str:
    analysis_id = uuid.uuid4().hex
    data = {k: result.get(k) for k in FIELDS}
    await redis.set(_key(owner, analysis_id), json.dumps(data, ensure_ascii=False), ex=PHOTO_TTL_SECONDS)
    return analysis_id


async def load(redis, owner: str, analysis_id: str | None) -> dict[str, Any] | None:
    """번호로 분석 결과를 꺼낸다. 형식이 틀리거나, 다른 사람 것이거나, 시간이 지나 사라졌으면 None."""
    if not analysis_id or not ID_PATTERN.match(analysis_id):
        return None
    raw = await redis.get(_key(owner, analysis_id))
    if not raw:
        return None
    data = json.loads(raw)
    return {k: data.get(k) for k in FIELDS}


def merge_features(features: dict[str, Any] | None, photo: dict[str, Any] | None) -> dict[str, Any]:
    """설명 글에서 뽑은 특징(llm_features)에 쓸 만한 사진의 특징을 더한다. 글에서 뽑은 값이 있으면 그것을 앞세운다."""
    merged = dict(features or {})
    if not photo or not photo.get("suitable"):
        return merged
    merged["colors"] = list(dict.fromkeys([*(merged.get("colors") or []), *(photo.get("colors") or [])]))
    merged["marks"] = list(dict.fromkeys([*(merged.get("marks") or []), *(photo.get("marks") or [])]))
    if not merged.get("sex") and photo.get("sex"):
        merged["sex"] = photo["sex"]
    if not merged.get("breed") and photo.get("breed"):
        merged["breed"] = photo["breed"]
    return merged
