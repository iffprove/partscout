# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RawPost(BaseModel):
    source: str
    source_post_id: str
    url: str
    lang_guess: str | None = None
    posted_at: datetime | None = None
    raw_text: str
    raw_html: str | None = None


class Vehicle(BaseModel):
    make: str | None = None
    model: str | None = None
    year_from: int | None = None
    year_to: int | None = None


class Part(BaseModel):
    name_en: str
    name_original: str
    part_numbers: list[str] = Field(default_factory=list)


class Price(BaseModel):
    value: float | None = None
    currency: str | None = None


class ExtractedListing(BaseModel):
    kind: Literal["wtb", "fs", "other"]
    vehicle: Vehicle
    part: Part
    condition: Literal["used", "new", "any", "unknown"]
    price: Price | None = None
    location_country: str | None = None
    confidence: float = 0.0


class Match(BaseModel):
    wtb_id: int
    fs_id: int
    tier: Literal["part_number", "fuzzy"]
    score: float
    llm_verdict: Literal["match", "likely", "no"] | None = None
