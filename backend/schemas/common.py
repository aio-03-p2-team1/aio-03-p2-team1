"""Shared value types used by model and API schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Color = Literal["갈색", "흰색", "검정", "회색", "크림", "노랑", "주황", "황갈색", "삼색", "고등어"]
Sex = Literal["M", "F", ""]
Species = Literal["dog", "cat", "etc", ""]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
