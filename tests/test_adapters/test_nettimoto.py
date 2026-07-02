# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from partscout.adapters.nettimoto import NettimotoAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures" / "nettimoto"
_BASE_URL = "https://www.nettivaraosa.com/en/moottoripyoran-varaosat-ja-tarvikkeet"

_ADAPTER = NettimotoAdapter(config=None)

_F_YAMAHA = "Nettivaraosa - Yamaha 750 - Motorcycle spare parts and accessories - Nettivaraosa.html"
_F_HONDA = (
    "Nettivaraosa - Honda Cb1000r 2010 - Powercommander V 2009-2010"
    " - Motorcycle spare parts and accessories - Nettivaraosa.html"
)
_F_SUZUKI = (
    "Nettivaraosa - Suzuki Ts 1985 - 125"
    " - Motorcycle spare parts and accessories - Nettivaraosa.html"
)


class TestNettimotoParser:
    def test_yamaha_750_returns_post(self) -> None:
        html = (FIXTURES / _F_YAMAHA).read_text(encoding="utf-8")
        post = _ADAPTER._parse_listing_page(html, f"{_BASE_URL}/3239717")
        assert post is not None
        assert post.source == "nettimoto"
        assert post.source_post_id == "3239717"
        assert "Yamaha" in post.raw_text
        assert "200" in post.raw_text  # price
        assert post.lang_guess == "fi"

    def test_honda_cb1000r_returns_post(self) -> None:
        html = (FIXTURES / _F_HONDA).read_text(encoding="utf-8")
        post = _ADAPTER._parse_listing_page(html, f"{_BASE_URL}/3238959")
        assert post is not None
        assert post.source_post_id == "3238959"
        assert "Honda" in post.raw_text
        assert "240" in post.raw_text

    def test_suzuki_ts_1985_returns_post(self) -> None:
        html = (FIXTURES / _F_SUZUKI).read_text(encoding="utf-8")
        post = _ADAPTER._parse_listing_page(html, f"{_BASE_URL}/3238765")
        assert post is not None
        assert "Suzuki" in post.raw_text
        assert "1985" in post.raw_text
        assert post.raw_html is not None

    def test_raw_html_stored(self) -> None:
        html = (FIXTURES / _F_YAMAHA).read_text(encoding="utf-8")
        post = _ADAPTER._parse_listing_page(html, f"{_BASE_URL}/3239717")
        assert post is not None
        assert post.raw_html == html
