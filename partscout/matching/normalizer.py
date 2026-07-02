# -*- coding: utf-8 -*-
from __future__ import annotations

import re

# Brand alias table: maps any variant to the canonical form.
BRAND_ALIASES: dict[str, str] = {
    "hd": "Harley-Davidson",
    "harley": "Harley-Davidson",
    "harley davidson": "Harley-Davidson",
    "harley-davidson": "Harley-Davidson",
    "bmw": "BMW",
    "kawa": "Kawasaki",
    "kawasaki": "Kawasaki",
    "yam": "Yamaha",
    "yamaha": "Yamaha",
    "honda": "Honda",
    "suzuki": "Suzuki",
    "ktm": "KTM",
    "triumph": "Triumph",
    "ducati": "Ducati",
    "aprilia": "Aprilia",
    "mv agusta": "MV Agusta",
    "mv": "MV Agusta",
    "husqvarna": "Husqvarna",
    "husq": "Husqvarna",
    "royal enfield": "Royal Enfield",
    "re": "Royal Enfield",  # ambiguous — only used if context is clear
}

# Currency normalization: maps symbols and lowercase codes to ISO 4217.
CURRENCY_ALIASES: dict[str, str] = {
    "€": "EUR",
    "eur": "EUR",
    "$": "USD",
    "usd": "USD",
    "£": "GBP",
    "gbp": "GBP",
    "kr": "SEK",  # default for Nordic context; overridden by country hints
    "sek": "SEK",
    "nok": "NOK",
    "dkk": "DKK",
    "pln": "PLN",
    "zł": "PLN",
    "czk": "CZK",
    "huf": "HUF",
    "chf": "CHF",
}


def normalize_part_number(raw: str) -> str:
    """Strip dashes, spaces, dots, and lowercase for exact-match comparison."""
    return re.sub(r"[\s\-./]", "", raw).lower()


def normalize_brand(raw: str) -> str:
    key = raw.strip().lower()
    return BRAND_ALIASES.get(key, raw.strip())


def normalize_currency(raw: str) -> str:
    """Return ISO 4217 currency code, or the original string if unknown."""
    return CURRENCY_ALIASES.get(raw.strip().lower(), raw.strip().upper())


def normalize_identifiers(identifiers: list[str]) -> set[str]:
    return {normalize_part_number(p) for p in identifiers if p.strip()}


def brands_compatible(a: str | None, b: str | None) -> bool:
    """True if both makes are the same after aliasing, or either is unknown."""
    if not a or not b:
        return True
    return normalize_brand(a).lower() == normalize_brand(b).lower()


def years_overlap(
    a_from: int | None,
    a_to: int | None,
    b_from: int | None,
    b_to: int | None,
) -> bool:
    """True if the year ranges [a_from, a_to] and [b_from, b_to] overlap,
    or if either range is completely unknown (both bounds null)."""
    a_unknown = a_from is None and a_to is None
    b_unknown = b_from is None and b_to is None
    if a_unknown or b_unknown:
        return True
    # Treat single-bound ranges as open-ended
    lo_a = a_from if a_from is not None else 1900
    hi_a = a_to if a_to is not None else 2100
    lo_b = b_from if b_from is not None else 1900
    hi_b = b_to if b_to is not None else 2100
    return lo_a <= hi_b and lo_b <= hi_a
