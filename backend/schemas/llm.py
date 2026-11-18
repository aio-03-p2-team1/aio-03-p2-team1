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


class RefinedDescriptionModelResponse(StrictSchema):
    """Template fields and searchable facts, extracted from one text/photo request."""

    fur_color: str
    features: str
    situation: str
    other: str
    text_colors: list[Color]
    text_sex: Sex
    text_marks: list[str]
    photo_suitable: bool
    photo_colors: list[Color]
    photo_sex: Sex
    photo_marks: list[str]


class RefinedDescriptionResult(StrictSchema):
    description: str
    features: dict[str, object]
    photo_features: dict[str, object] | None
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
