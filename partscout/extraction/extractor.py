# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from typing import Any

from partscout.extraction.llm import EXTRACTION_TOOL, LLMClient
from partscout.extraction.prompts import EXTRACTION_SYSTEM, EXTRACTION_USER_TEMPLATE
from partscout.extraction.schemas import ExtractedListing, Part, Price, RawPost, Vehicle

logger = logging.getLogger(__name__)


class Extractor:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def extract(self, post: RawPost, country_hint: str = "") -> ExtractedListing | None:
        user = EXTRACTION_USER_TEMPLATE.format(
            source=post.source,
            country=country_hint or "unknown",
            url=post.url,
            text=post.raw_text,
        )
        try:
            raw: dict[str, Any] = self._client.call(
                system=EXTRACTION_SYSTEM,
                user=user,
                tool=EXTRACTION_TOOL,
            )
        except Exception:
            logger.exception("LLM extraction failed for %s", post.url)
            return None

        return self._coerce(raw)

    # ------------------------------------------------------------------

    def _coerce(self, raw: dict[str, Any]) -> ExtractedListing:
        v = raw.get("vehicle") or {}
        vehicle = Vehicle(
            make=v.get("make"),
            model=v.get("model"),
            year_from=v.get("year_from"),
            year_to=v.get("year_to"),
        )

        p = raw.get("part") or {}
        part = Part(
            name_en=p.get("name_en", ""),
            name_original=p.get("name_original", ""),
            part_numbers=p.get("part_numbers") or [],
        )

        price_raw = raw.get("price")
        price: Price | None = None
        if isinstance(price_raw, dict):
            price = Price(
                value=price_raw.get("value"),
                currency=price_raw.get("currency"),
            )

        return ExtractedListing(
            kind=raw.get("kind", "other"),
            vehicle=vehicle,
            part=part,
            condition=raw.get("condition", "unknown"),
            price=price,
            location_country=raw.get("location_country"),
            confidence=float(raw.get("confidence", 0.0)),
        )
