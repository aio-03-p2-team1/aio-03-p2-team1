"""Pydantic schemas for HTTP requests and responses."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.schemas.common import Color, MAX_IMAGE_BYTES, PhotoAnalysisReason, Sex, Species, StrictSchema

MAX_POST_PHOTO_BYTES = 400 * 1024


class SearchCriteria(BaseModel):
    species: str | None = Field(default=None, max_length=10)
    region: str | None = Field(default=None, max_length=30)
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    lost_date: str | None = Field(default=None, max_length=10)
    pet_name: str | None = Field(default=None, max_length=30)
    breed: str | None = Field(default=None, max_length=40)
    breed_code: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=40)
    sex: str | None = Field(default=None, max_length=4)
    age: str | None = Field(default=None, max_length=20)
    size: str | None = Field(default=None, max_length=20)
    lost_place: str | None = Field(default=None, max_length=100)
    # 사용자가 지도에서 찍은 실종 위치 좌표(반경 중심). 한국 범위를 벗어나면 422. 없으면 서버가 lost_place 주소로 좌표를 구한다.
    lost_lat: float | None = Field(default=None, ge=33.0, le=39.0)
    lost_lng: float | None = Field(default=None, ge=124.0, le=132.0)
    radius_step: int | None = Field(default=None, ge=0, le=3)  # 반경 넓히기에 동의한 단계(검색 요청에서만 사용)
    description: str | None = Field(default=None, max_length=1000)


class SearchBody(BaseModel):
    criteria: SearchCriteria = Field(default_factory=SearchCriteria)
    thread_id: str | None = Field(default=None, max_length=64, pattern=r"^[0-9a-f]{8,64}$")
    profile_id: str | None = Field(default=None, max_length=40, pattern=r"^[\w-]{1,40}$")
    reflection_enabled: bool = True
    # 에이전트 요청에 사용자가 '잘 모르겠어요'라고 답한 항목. 같은 대화에서 다시 묻지 않는다.
    # 사진 분석 결과 번호(/photo-analysis 응답의 analysis_id). 서버가 보관한 결과를 꺼내 특징·판단에 쓴다.
    photo_analysis_id: str | None = Field(None, pattern=r"^[0-9a-f]{32}$")
    # 서버가 다듬기 응답과 검색 특징을 저장한 소유자 한정 번호.
    refinement_id: str | None = Field(None, pattern=r"^[0-9a-f]{32}$")
    declined: list[Literal["photo", "color", "size", "sex", "marks"]] = Field(default_factory=list, max_length=5)


class RefineDescriptionBody(BaseModel):
    description: str = Field(default="", max_length=1000)
    image_base64: str | None = Field(None, min_length=1, max_length=((MAX_IMAGE_BYTES + 2) // 3) * 4)
    post_id: str | None = Field(None, min_length=1, max_length=64)

    @field_validator("description")
    @classmethod
    def _strip_description(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _one_image_source(self):
        if self.image_base64 is not None and self.post_id is not None:
            raise ValueError("image_base64 와 post_id 를 함께 보낼 수 없습니다")
        if not self.description and self.image_base64 is None and self.post_id is None:
            raise ValueError("description 또는 사진이 필요합니다")
        return self


class RefineDescriptionResponse(StrictSchema):
    description: str
    refinement_id: str
    photo_used: bool


class PhotoAnalysisBody(BaseModel):
    # 둘 중 하나만: 직접 올린 사진(base64) 또는 실종 정보 게시판 글 ID(회원 글·분실 신고). 글 ID 면 서버가 그 글의 사진을 꺼낸다.
    image_base64: str | None = Field(None, min_length=1, max_length=((MAX_IMAGE_BYTES + 2) // 3) * 4)
    post_id: str | None = Field(None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _one_source(self):
        if (self.image_base64 is None) == (self.post_id is None):
            raise ValueError("image_base64 와 post_id 중 하나만 보내야 합니다")
        return self


class RegisterBody(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    name: str
    email: str
    is_admin: bool = False  # 화면에서 관리자 메뉴를 보일지만 정한다. 권한은 서버가 요청마다 다시 확인한다


class SavedSearchBody(BaseModel):
    title: str = Field(default="", max_length=40)
    criteria: SearchCriteria


class MemoryBody(BaseModel):
    profile_id: str = Field(pattern=r"^[\w-]{1,40}$")
    # 사용자가 직접 확인한 특징만 저장한다(모델 추정값 금지).
    confirmed: SearchCriteria


class PostBody(BaseModel):
    pet_name: str = Field(min_length=1, max_length=20)
    species: Literal["dog", "cat", "etc"]
    region: str = Field(min_length=1, max_length=20)
    lost_place: str = Field(default="", max_length=100)
    lost_date: date
    breed: str = Field(default="", max_length=30)
    breed_code: str = Field(default="", max_length=20)
    description: str = Field(min_length=5, max_length=1000)
    photo: str | None = Field(default=None, max_length=MAX_POST_PHOTO_BYTES * 2)

    @field_validator("pet_name", "region", "lost_place", "breed", "breed_code", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class PostUpdateBody(BaseModel):
    pet_name: str = Field(min_length=1, max_length=20)
    species: Literal["dog", "cat", "etc"]
    region: str = Field(min_length=1, max_length=20)
    lost_place: str = Field(default="", max_length=100)
    lost_date: date
    breed: str = Field(default="", max_length=30)
    breed_code: str = Field(default="", max_length=20)
    description: str = Field(min_length=5, max_length=1000)

    @field_validator("pet_name", "region", "lost_place", "breed", "description", "breed_code")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class CommentBody(BaseModel):
    body: str = Field(min_length=1, max_length=500)

    @field_validator("body")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class PhotoAnalysisResponse(StrictSchema):
    """Public photo analysis response; the frontend maps reason codes to guidance."""

    animal_present: bool
    identifiable: bool
    center_subject_clear: bool
    suitable: bool
    species: Species
    colors: list[Color]
    breed_code: str
    breed: str
    sex: Sex
    marks: list[str]
    reason_code: PhotoAnalysisReason | None
    analysis_ms: int = Field(ge=0)
    # 서버에 잠시 보관한 분석 결과 번호. 검색 요청의 photo_analysis_id 로 보내면 서버가 이 결과를 쓴다(보관 실패 시 None).
    analysis_id: str | None = None
