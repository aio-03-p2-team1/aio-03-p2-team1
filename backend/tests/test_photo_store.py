"""사진 분석 결과 보관: 사용자별 격리, 형식 검사, 특징 합치기, 검색 요청과 연결."""

import asyncio

import fakeredis

from backend.agent import photo_store

RESULT = {"suitable": True, "species": "dog", "breed": "", "breed_code": "", "colors": ["흰색"], "sex": "M",
          "marks": ["빨간 목줄"], "reason_code": None, "animal_present": True}


def test_save_and_load_is_owner_scoped():
    redis = fakeredis.FakeAsyncRedis()
    analysis_id = asyncio.run(photo_store.save(redis, "owner-a", RESULT))
    loaded = asyncio.run(photo_store.load(redis, "owner-a", analysis_id))
    assert loaded == {k: RESULT[k] for k in photo_store.FIELDS}  # 필요한 특징만 보관
    assert asyncio.run(photo_store.load(redis, "owner-b", analysis_id)) is None  # 다른 사람은 못 읽음
    assert asyncio.run(photo_store.load(redis, "owner-a", "../evil")) is None
    assert asyncio.run(photo_store.load(redis, "owner-a", None)) is None


def test_merge_features_only_suitable_photo():
    merged = photo_store.merge_features({"colors": ["갈색"], "sex": "F", "marks": []}, RESULT)
    assert merged == {"colors": ["갈색", "흰색"], "sex": "F", "marks": ["빨간 목줄"]}  # 글에서 뽑은 성별을 앞세움
    assert photo_store.merge_features({"colors": ["갈색"]}, {**RESULT, "suitable": False}) == {"colors": ["갈색"]}
