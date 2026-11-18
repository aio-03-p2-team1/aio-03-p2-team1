"""Validated inputs and outputs at the language model boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from backend.schemas.common import Color, MAX_IMAGE_BYTES, PhotoAnalysisReason, Sex, Species, StrictSchema


class FeatureExtractionRequest(StrictSchema):
    description: str = Field(min_length=1, max_length=1000)

    @field_validator("description")
    @classmethod
    def description_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("description must not be blank")
        return value


class PhotoAnalysisRequest(StrictSchema):
    image: bytes = Field(min_length=1, max_length=MAX_IMAGE_BYTES)
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]


class FeatureExtractionModelResponse(StrictSchema):
    colors: list[Color]
    sex: Sex
    marks: list[str]


class FeatureExtractionResult(StrictSchema):
    colors: list[Color]
    sex: Sex
    marks: list[str]
    model: str
    prompt_version: str


class ReviewConflict(StrictSchema):
    """글과 사진 분석이 어긋난 항목. 최종 특징에는 글의 값을 쓴다."""

    item: str
    text_value: str
    photo_value: str


class InputReviewModelResponse(StrictSchema):
    """검색 전 입력 검토(글 + 서버가 보관한 사진 분석 결과)를 한 번의 구조화 호출로 받는다."""

    fur_color: str
    features: str
    situation: str
    other: str
    colors: list[Color]
    sex: Sex
    marks: list[str]
    duplicates: list[str]
    conflicts: list[ReviewConflict]
    action: Literal["search", "ask"]
    question: str
    message: str


class InputReviewResult(StrictSchema):
    organized_text: str
    features: dict[str, object]
    duplicates: list[str]
    conflicts: list[dict[str, str]]
    action: Literal["search", "ask"]
    question: str
    message: str
    prompt_version: str


class PhotoConfidence(StrictSchema):
    animal_present: float
    identifiable: float
    center_subject_clear: float
    species: float
    breed_code: float
    sex: float

    @model_validator(mode="after")
    def confidence_values_are_normalized(self) -> PhotoConfidence:
        if any(not 0 <= value <= 1 for value in self.model_dump().values()):
            raise ValueError("confidence values must be between 0 and 1")
        return self


class PhotoFeature(StrictSchema):
    value: str
    confidence: float

    @field_validator("confidence")
    @classmethod
    def confidence_is_normalized(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class PhotoAnalysisModelResponse(StrictSchema):
    animal_present: bool
    identifiable: bool
    center_subject_clear: bool
    confidence: PhotoConfidence
    species: Species
    colors: list[PhotoFeature]
    breed_code: str
    sex: Sex
    marks: list[PhotoFeature]


class PhotoAnalysisResult(StrictSchema):
    """Normalized analysis result before it is shaped for the HTTP API."""

    animal_present: bool
    identifiable: bool
    center_subject_clear: bool
    suitable: bool
    reason_code: PhotoAnalysisReason | None
    breed: str
    species: Species
    colors: list[Color]
    breed_code: str
    sex: Sex
    marks: list[str]
