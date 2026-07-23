# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from partscout.adapters.sporthoj import SporthojAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sporthoj"

_ADAPTER = SporthojAdapter(config=None)

_F_SALJES_BOOTS = "Sporthoj - SIDI Cobra strl 45 (saljes).html"
_F_SALJES_SEAT = "Sporthoj - Hogsadel Suzuki DL650 (saljes).html"
_F_KOPES_APRILIA = "Sporthoj - Aprilia el Suzuki rs-rgv kopes (kopes).html"
_INDEX_SALJES = "index_saljes_sample.html"
_INDEX_KOPES = "index_kopes_sample.html"

_URL_BOOTS = "https://www.sporthoj.com/annonser/id/10898"
_URL_SEAT = "https://www.sporthoj.com/annonser/id/10877"
_URL_APRILIA = "https://www.sporthoj.com/annonser/id/10890"


class TestSporthojParser:
    def test_saljes_boots_returns_post(self) -> None:
        html = (FIXTURES / _F_SALJES_BOOTS).read_text(encoding="utf-8")
        post = _ADAPTER._parse_listing_page(html, _URL_BOOTS)
        assert post is not None
        assert post.source == "sporthoj"
        assert post.source_post_id == "10898"
        assert "SIDI" in post.raw_text
        assert "900" in post.raw_text
        assert "Västra Götaland" in post.raw_text
        assert post.lang_guess == "sv"

    def test_saljes_seat_returns_post(self) -> None:
        html = (FIXTURES / _F_SALJES_SEAT).read_text(encoding="utf-8")
        post = _ADAPTER._parse_listing_page(html, _URL_SEAT)
        assert post is not None
        assert post.source_post_id == "10877"
        assert "Suzuki DL650" in post.raw_text
        assert "700" in post.raw_text
        assert "Stockholm" in post.raw_text

    def test_kopes_aprilia_returns_post_with_vehicle_attributes(self) -> None:
        html = (FIXTURES / _F_KOPES_APRILIA).read_text(encoding="utf-8")
        post = _ADAPTER._parse_listing_page(html, _URL_APRILIA)
        assert post is not None
        assert post.source_post_id == "10890"
        assert "Aprilia" in post.raw_text
        assert "1998" in post.raw_text
        assert "RS250 RGV250" in post.raw_text
        # Nominal "1 :-" placeholder price on WTB ads should not be reported as a real price
        assert "Price: 1 SEK" not in post.raw_text

    def test_raw_html_stored(self) -> None:
        html = (FIXTURES / _F_SALJES_BOOTS).read_text(encoding="utf-8")
        post = _ADAPTER._parse_listing_page(html, _URL_BOOTS)
        assert post is not None
        assert post.raw_html == html

    def test_parse_index_page_extracts_unique_item_urls_saljes(self) -> None:
        html = (FIXTURES / _INDEX_SALJES).read_text(encoding="utf-8")
        urls = _ADAPTER._parse_index_page(html)
        assert len(urls) > 0
        assert len(urls) == len(set(urls))
        assert _URL_BOOTS in urls

    def test_parse_index_page_extracts_unique_item_urls_kopes(self) -> None:
        html = (FIXTURES / _INDEX_KOPES).read_text(encoding="utf-8")
        urls = _ADAPTER._parse_index_page(html)
        assert _URL_APRILIA in urls

    def test_parse_listing_page_returns_none_without_info_section(self) -> None:
        html = "<html><body><h1>Title</h1></body></html>"
        post = _ADAPTER._parse_listing_page(html, _URL_BOOTS)
        assert post is None
