"""Shared value types used by model and API schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.normalization.color import ColorDictionary

MAX_IMAGE_BYTES = 8 * 1024 * 1024
Color = Literal[*ColorDictionary.allowed_values()]
Sex = Literal["M", "F", ""]
Species = Literal["dog", "cat", "etc", ""]
PhotoAnalysisReason = Literal["animal_not_detected", "appearance_unclear", "subject_not_distinct"]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
