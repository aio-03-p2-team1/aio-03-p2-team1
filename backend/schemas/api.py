"""Pydantic schemas for HTTP requests and responses."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.schemas.common import Color, Sex, Species, StrictSchema


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


class PhotoAnalysisResponse(StrictSchema):
    """Public photo analysis response; internal reason codes are localized by the API."""

    animal_present: bool
    identifiable: bool
    center_subject_clear: bool
    suitable: bool
    species: Species
    colors: list[Color]
    breed: str
    sex: Sex
    marks: list[str]
    message: str
    model: str
    prompt_version: str
    analysis_ms: int
