# -*- coding: utf-8 -*-
"""Extraction tests.

Unit tests: schema coercion + prompt building (no LLM calls).
Integration tests (marked): real LLM call + field-level accuracy on labeled.jsonl.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from partscout.extraction.extractor import Extractor
from partscout.extraction.schemas import RawPost

LABELED = Path(__file__).parent / "labeled.jsonl"


def _mock_extractor(tool_result: dict[str, Any]) -> Extractor:
    client = MagicMock()
    client.call.return_value = tool_result
    return Extractor(client)


class TestExtractorCoercion:
    def test_fs_basic(self) -> None:
        ext = _mock_extractor({
            "kind": "fs",
            "vehicle": {"make": "Honda", "model": "CB750", "year_from": None, "year_to": None},
            "part": {
                "name_en": "carburettor",
                "name_original": "kaasutinjärjestelmä",
                "part_numbers": ["16010-300-015"],
            },
            "condition": "used",
            "price": {"value": 80.0, "currency": "EUR"},
            "location_country": "FI",
            "confidence": 0.9,
        })
        post = RawPost(source="test", source_post_id="1", url="http://x", raw_text="test")
        result = ext.extract(post)
        assert result is not None
        assert result.kind == "fs"
        assert result.vehicle.make == "Honda"
        assert result.part.part_numbers == ["16010-300-015"]
        assert result.price is not None
        assert result.price.value == 80.0
        assert result.price.currency == "EUR"

    def test_wtb_no_price(self) -> None:
        ext = _mock_extractor({
            "kind": "wtb",
            "vehicle": {"make": "Yamaha", "model": "FZR", "year_from": None, "year_to": None},
            "part": {
                "name_en": "alternator connectors",
                "name_original": "laturin sähköliittimet",
                "part_numbers": [],
            },
            "condition": "used",
            "price": None,
            "location_country": "FI",
            "confidence": 0.85,
        })
        post = RawPost(source="test", source_post_id="2", url="http://x", raw_text="test")
        result = ext.extract(post)
        assert result is not None
        assert result.kind == "wtb"
        assert result.price is None

    def test_other_kind(self) -> None:
        ext = _mock_extractor({
            "kind": "other",
            "vehicle": {"make": None, "model": None, "year_from": None, "year_to": None},
            "part": {"name_en": "", "name_original": "", "part_numbers": []},
            "condition": "unknown",
            "price": None,
            "location_country": None,
            "confidence": 0.3,
        })
        post = RawPost(source="test", source_post_id="3", url="http://x", raw_text="test")
        result = ext.extract(post)
        assert result is not None
        assert result.kind == "other"

    def test_llm_failure_returns_none(self) -> None:
        client = MagicMock()
        client.call.side_effect = RuntimeError("network error")
        ext = Extractor(client)
        post = RawPost(source="test", source_post_id="4", url="http://x", raw_text="test")
        result = ext.extract(post)
        assert result is None


@pytest.mark.integration
class TestExtractionAccuracy:
    """Calls the real LLM — skipped unless ANTHROPIC_API_KEY is set and --integration flag used."""

    def _load_labeled(self) -> list[dict[str, Any]]:
        rows = []
        for line in LABELED.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows

    def test_kind_accuracy(self, real_extractor: Extractor) -> None:
        rows = self._load_labeled()
        wrong = 0
        for row in rows:
            post = RawPost(
                source=row["source"],
                source_post_id=row["id"],
                url="http://test",
                raw_text=row["text"],
            )
            country = row.get("expected", {}).get("location_country", "")
            result = real_extractor.extract(post, country_hint=country)
            expected_kind = row["expected"]["kind"]
            if result is None or result.kind != expected_kind:
                wrong += 1
                got = result.kind if result else None
                print(f"FAIL {row['id']}: expected kind={expected_kind!r} got {got!r}")
        total = len(rows)
        accuracy = (total - wrong) / total
        assert accuracy >= 0.90, f"Kind accuracy {accuracy:.0%} < 90% ({wrong}/{total} wrong)"

    def test_price_accuracy(self, real_extractor: Extractor) -> None:
        rows = [r for r in self._load_labeled() if "price_value" in r["expected"]]
        wrong = 0
        for row in rows:
            post = RawPost(
                source=row["source"],
                source_post_id=row["id"],
                url="http://test",
                raw_text=row["text"],
            )
            result = real_extractor.extract(post)
            expected = row["expected"]["price_value"]
            actual = result.price.value if result and result.price else None
            if actual != expected:
                wrong += 1
        accuracy = (len(rows) - wrong) / len(rows) if rows else 1.0
        assert accuracy >= 0.85, f"Price accuracy {accuracy:.0%} < 85%"


@pytest.fixture
def real_extractor():  # type: ignore[no-untyped-def]
    import os

    from partscout.extraction.llm import build_client
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    client = build_client("anthropic", "claude-haiku-4-5-20251001", api_key)
    return Extractor(client)
