# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from partscout.adapters import ss_lv
from partscout.adapters.ss_lv import SsLvAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ss_lv"

_ADAPTER = SsLvAdapter(config=None)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


class _FakeClient:
    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        for key, html in self._pages.items():
            if url.endswith(key):
                return _FakeResponse(html)
        raise AssertionError(f"unexpected URL requested: {url}")


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


class TestFetchHistory:
    def test_marks_posts_historical(self, monkeypatch: pytest.MonkeyPatch) -> None:
        archive_html = (FIXTURES / "archive_other_parts.html").read_text(
            encoding="utf-8", errors="replace"
        )
        item_html = (FIXTURES / "item_bagazas_kaste.html").read_text(
            encoding="utf-8", errors="replace"
        )
        urls = _ADAPTER._parse_category_page(archive_html)
        assert urls, "fixture should contain at least one archived listing"

        pages = {"other-parts/": archive_html}
        for url in urls:
            pages[url.rsplit("/", 1)[-1]] = item_html
        monkeypatch.setattr(ss_lv.httpx, "Client", lambda **_: _FakeClient(pages))
        monkeypatch.setattr(ss_lv.time, "sleep", lambda *_: None)

        posts = list(_ADAPTER.fetch_history(since=date(2024, 1, 1)))

        assert len(posts) == len(urls)
        assert all(p.historical for p in posts)
