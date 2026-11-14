"""Pydantic schemas shared by the HTTP API routers."""

from __future__ import annotations

from pydantic import BaseModel, Field


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
