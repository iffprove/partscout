# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from partscout.adapters.ss_lv import SsLvAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ss_lv"

_ADAPTER = SsLvAdapter(config=None)


class TestSsLvParser:
    def test_category_page_returns_item_urls(self) -> None:
        html = (FIXTURES / "category_other_parts.html").read_text(
            encoding="utf-8", errors="replace"
        )
        urls = _ADAPTER._parse_category_page(html)
        assert len(urls) > 0
        assert all(url.startswith("https://www.ss.lv/msg/") for url in urls)

    def test_bagazas_kaste_item_parsed(self) -> None:
        html = (FIXTURES / "item_bagazas_kaste.html").read_text(
            encoding="utf-8", errors="replace"
        )
        url = (
            "https://www.ss.lv/msg/lv/transport/moto-transport/"
            "spare-parts/other-parts/bdcfeo.html"
        )
        post = _ADAPTER._parse_item_page(html, url)
        assert post is not None
        assert post.source == "ss_lv"
        assert post.source_post_id == "bdcfeo"
        assert "Bagāžas" in post.raw_text
        assert "236" in post.raw_text
        assert post.lang_guess == "lv"
        assert post.raw_html == html

    def test_virzulis_item_parsed(self) -> None:
        html = (FIXTURES / "item_virzulis_pirksts.html").read_text(
            encoding="utf-8", errors="replace"
        )
        url = (
            "https://www.ss.lv/msg/lv/transport/moto-transport/"
            "spare-parts/engines-and-parts/bhjpcg.html"
        )
        post = _ADAPTER._parse_item_page(html, url)
        assert post is not None
        assert post.source_post_id == "bhjpcg"
        assert "virzulis" in post.raw_text.lower()
        assert "200" in post.raw_text

    def test_empty_page_returns_none(self) -> None:
        post = _ADAPTER._parse_item_page("<html><body></body></html>", "u")
        assert post is None
