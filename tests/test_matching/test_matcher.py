# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from partscout.matching.normalizer import (
    brands_compatible,
    normalize_brand,
    normalize_currency,
    normalize_identifiers,
    normalize_part_number,
    years_overlap,
)

GOLDEN = Path(__file__).parent / "golden_pairs.jsonl"


def _load_golden() -> list[dict]:  # type: ignore[type-arg]
    rows = []
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


class TestNormalizer:
    def test_strip_dashes(self) -> None:
        assert normalize_part_number("16010-300-015") == "16010300015"

    def test_strip_spaces(self) -> None:
        assert normalize_part_number("59093 91") == "5909391"

    def test_lowercase(self) -> None:
        assert normalize_part_number("ABC-123") == "abc123"

    def test_empty_string(self) -> None:
        assert normalize_part_number("") == ""

    def test_identifiers_set(self) -> None:
        ids = normalize_identifiers(["16010-300-015", "16010.300.015"])
        assert ids == {"16010300015"}

    def test_brand_harley_alias(self) -> None:
        assert normalize_brand("HD") == "Harley-Davidson"
        assert normalize_brand("harley") == "Harley-Davidson"
        assert normalize_brand("Harley-Davidson") == "Harley-Davidson"

    def test_brand_unknown_passthrough(self) -> None:
        assert normalize_brand("Aprilia") == "Aprilia"


class TestCurrencyNormalization:
    def test_euro_symbol(self) -> None:
        assert normalize_currency("€") == "EUR"

    def test_eur_lowercase(self) -> None:
        assert normalize_currency("eur") == "EUR"

    def test_dollar(self) -> None:
        assert normalize_currency("$") == "USD"

    def test_kr_to_sek(self) -> None:
        assert normalize_currency("kr") == "SEK"

    def test_pln_zloty(self) -> None:
        assert normalize_currency("zł") == "PLN"

    def test_unknown_passthrough(self) -> None:
        assert normalize_currency("XYZ") == "XYZ"


class TestBrandsCompatible:
    def test_same_canonical(self) -> None:
        assert brands_compatible("Honda", "honda")

    def test_alias_match(self) -> None:
        assert brands_compatible("HD", "Harley-Davidson")

    def test_different_makes(self) -> None:
        assert not brands_compatible("Yamaha", "Kawasaki")

    def test_none_is_wildcard(self) -> None:
        assert brands_compatible(None, "Yamaha")
        assert brands_compatible("Honda", None)
        assert brands_compatible(None, None)


class TestYearsOverlap:
    def test_both_unknown(self) -> None:
        assert years_overlap(None, None, None, None)

    def test_one_fully_unknown(self) -> None:
        assert years_overlap(None, None, 2010, 2015)

    def test_overlapping_ranges(self) -> None:
        assert years_overlap(2009, 2012, 2011, 2014)

    def test_adjacent_ranges(self) -> None:
        assert years_overlap(2009, 2012, 2012, 2015)

    def test_non_overlapping(self) -> None:
        assert not years_overlap(2017, 2021, 2013, 2016)

    def test_open_ended_low(self) -> None:
        assert years_overlap(1993, None, None, 2000)

    def test_single_year_matches(self) -> None:
        assert years_overlap(1991, 1991, 1989, 1995)


class TestTier1Matching:
    def test_true_match_part_number(self) -> None:
        wtb_ids = normalize_identifiers(["59093-91"])
        fs_ids = normalize_identifiers(["59093/91"])
        assert wtb_ids & fs_ids

    def test_near_miss_different_part_number(self) -> None:
        wtb_ids = normalize_identifiers(["59093-91"])
        fs_ids = normalize_identifiers(["59093-92"])
        assert not (wtb_ids & fs_ids)

    def test_no_identifiers_no_match(self) -> None:
        wtb_ids = normalize_identifiers([])
        fs_ids = normalize_identifiers(["59093-91"])
        assert not (wtb_ids & fs_ids)

    def test_multiple_identifiers_one_overlap(self) -> None:
        wtb_ids = normalize_identifiers(["AAA-111", "BBB-222"])
        fs_ids = normalize_identifiers(["CCC-333", "BBB-222"])
        assert wtb_ids & fs_ids


class TestGoldenPairs:
    """Deterministic checks on golden_pairs.jsonl using only normalizer logic.

    LLM-verification verdicts are tested in integration tests, not here.
    """

    def test_tp001_part_numbers_match(self) -> None:
        rows = _load_golden()
        row = next(r for r in rows if r["id"] == "tp-001")
        wtb_ids = normalize_identifiers(row["wtb"]["part_numbers"])
        fs_ids = normalize_identifiers(row["fs"]["part_numbers"])
        assert wtb_ids & fs_ids, "tp-001: part numbers should overlap after normalization"

    def test_tp002_harley_alias_and_part_number(self) -> None:
        rows = _load_golden()
        row = next(r for r in rows if r["id"] == "tp-002")
        # Part numbers match despite different formatting
        wtb_ids = normalize_identifiers(row["wtb"]["part_numbers"])
        fs_ids = normalize_identifiers(row["fs"]["part_numbers"])
        assert wtb_ids & fs_ids
        # Brand aliases are compatible
        assert brands_compatible(row["wtb"]["make"], row["fs"]["make"])

    def test_tp003_unknown_years_overlap(self) -> None:
        rows = _load_golden()
        row = next(r for r in rows if r["id"] == "tp-003")
        assert row["expected_years_overlap"] is True
        result = years_overlap(
            row["wtb"]["year_from"], row["wtb"]["year_to"],
            row["fs"]["year_from"], row["fs"]["year_to"],
        )
        assert result

    def test_nm001_incompatible_years(self) -> None:
        rows = _load_golden()
        row = next(r for r in rows if r["id"] == "nm-001")
        assert row["expected_years_overlap"] is False
        result = years_overlap(
            row["wtb"]["year_from"], row["wtb"]["year_to"],
            row["fs"]["year_from"], row["fs"]["year_to"],
        )
        assert not result

    def test_nm002_different_make(self) -> None:
        rows = _load_golden()
        row = next(r for r in rows if r["id"] == "nm-002")
        assert not brands_compatible(row["wtb"]["make"], row["fs"]["make"])

    def test_nm003_harley_not_kawasaki(self) -> None:
        rows = _load_golden()
        row = next(r for r in rows if r["id"] == "nm-003")
        assert not brands_compatible(row["wtb"]["make"], row["fs"]["make"])

    def test_nm004_different_part_numbers(self) -> None:
        rows = _load_golden()
        row = next(r for r in rows if r["id"] == "nm-004")
        wtb_ids = normalize_identifiers(row["wtb"]["part_numbers"])
        fs_ids = normalize_identifiers(row["fs"]["part_numbers"])
        assert not (wtb_ids & fs_ids), "nm-004: slightly different part numbers must not overlap"

    def test_nm005_open_ended_years_overlap(self) -> None:
        rows = _load_golden()
        row = next(r for r in rows if r["id"] == "nm-005")
        assert row["expected_years_overlap"] is True
        result = years_overlap(
            row["wtb"]["year_from"], row["wtb"]["year_to"],
            row["fs"]["year_from"], row["fs"]["year_to"],
        )
        assert result
