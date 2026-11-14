"""Pydantic schemas for HTTP requests and responses."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
    color: str | None = Field(default=None, max_length=40)
    sex: str | None = Field(default=None, max_length=4)
    age: str | None = Field(default=None, max_length=20)
    size: str | None = Field(default=None, max_length=20)
    lost_place: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class SearchBody(BaseModel):
    criteria: SearchCriteria = Field(default_factory=SearchCriteria)
    thread_id: str | None = Field(default=None, max_length=64, pattern=r"^[0-9a-f]{8,64}$")
    profile_id: str | None = Field(default=None, max_length=40, pattern=r"^[\w-]{1,40}$")
    reflection_enabled: bool = True


class PhotoAnalysisBody(BaseModel):
    image_base64: str = Field(min_length=1, max_length=((MAX_IMAGE_BYTES + 2) // 3) * 4)


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
    description: str = Field(min_length=5, max_length=1000)
    photo: str | None = Field(default=None, max_length=MAX_POST_PHOTO_BYTES * 2)

    @field_validator("pet_name", "region", "lost_place", "breed", "description")
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
    breed: str
    sex: Sex
    marks: list[str]
    reason_code: PhotoAnalysisReason | None
    analysis_ms: int = Field(ge=0)
