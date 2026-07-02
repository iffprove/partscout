# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from partscout.adapters.tori import ToriAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures" / "tori"

_ADAPTER = ToriAdapter(config=None)


class TestToriParser:
    def test_search_page_returns_item_urls(self) -> None:
        html = (FIXTURES / "search_moottoripyoran_varaosat.html").read_text(
            encoding="utf-8"
        )
        urls = _ADAPTER._parse_search_page(html)
        assert len(urls) > 0
        assert all(url.startswith("https://www.tori.fi/") for url in urls)
        assert "https://www.tori.fi/recommerce/forsale/item/19521704" in urls

    def test_syrjanen_racing_item_parsed(self) -> None:
        html = (FIXTURES / "item_syrjanen_racing.html").read_text(encoding="utf-8")
        url = "https://www.tori.fi/recommerce/forsale/item/19521704"
        post = _ADAPTER._parse_item_page(html, url)
        assert post is not None
        assert post.source == "tori"
        assert post.source_post_id == "19521704"
        assert "Varaosat" in post.raw_text
        assert "15" in post.raw_text
        assert post.lang_guess == "fi"
        assert post.raw_html == html

    def test_suzuki_sv650_item_parsed(self) -> None:
        html = (FIXTURES / "item_suzuki_sv650.html").read_text(encoding="utf-8")
        url = "https://www.tori.fi/recommerce/forsale/item/41760128"
        post = _ADAPTER._parse_item_page(html, url)
        assert post is not None
        assert post.source_post_id == "41760128"
        assert "Suzuki" in post.raw_text
        assert "SV650" in post.raw_text
        assert "250" in post.raw_text

    def test_missing_json_ld_returns_none(self) -> None:
        post = _ADAPTER._parse_item_page("<html><body>no data here</body></html>", "u")
        assert post is None
