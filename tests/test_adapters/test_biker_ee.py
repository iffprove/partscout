# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from partscout.adapters import biker_ee
from partscout.adapters.biker_ee import BikerEeAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures" / "forum"

_ADAPTER = BikerEeAdapter(config=None)


def _topic_html(title: str, datetime_str: str) -> str:
    return f"""
    <html><body>
    <div class="postbody">
      <h3>{title}</h3>
      <div class="content">Some part description text.</div>
      <time datetime="{datetime_str}">whenever</time>
      <strong>SomeUser</strong>
    </div>
    </body></html>
    """


def _index_html(topic_ids: list[int]) -> str:
    links = "\n".join(
        f'<a class="topictitle" href="viewtopic.php?f=90&amp;t={tid}">Topic {tid}</a>'
        for tid in topic_ids
    )
    return f"<html><body>{links}</body></html>"


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


class TestParseForumIndex:
    def test_dedupes_multiple_links_to_same_topic(self) -> None:
        # A real topic row renders a title link, an "unread" jump link, and a
        # last-post permalink — all pointing at the same topic but with
        # different query strings/params.
        html = """
        <html><body>
        <a class="topictitle" href="viewtopic.php?f=90&amp;t=12345">Some topic</a>
        <a href="viewtopic.php?f=90&amp;t=12345&amp;view=unread#unread">unread</a>
        <a href="viewtopic.php?p=98765#p98765">last post</a>
        </body></html>
        """
        urls = _ADAPTER._parse_forum_index(html)
        assert len(urls) == 1
        assert "t=12345" in urls[0]

    def test_drops_permalink_only_links_without_t_param(self) -> None:
        html = """
        <html><body>
        <a href="viewtopic.php?p=98765#p98765">post permalink only, no topic id</a>
        </body></html>
        """
        urls = _ADAPTER._parse_forum_index(html)
        assert urls == []

    def test_title_link_wins_even_when_unread_link_comes_first_in_markup(self) -> None:
        # Real biker.ee rows render the "unread" icon link before the title
        # link. The unread variant 404s without a live session — the title
        # link must be picked regardless of anchor order.
        html = """
        <html><body>
        <a href="viewtopic.php?f=90&amp;t=12345&amp;view=unread#unread">unread</a>
        <a class="topictitle" href="viewtopic.php?f=90&amp;t=12345">Some topic</a>
        </body></html>
        """
        urls = _ADAPTER._parse_forum_index(html)
        assert len(urls) == 1
        assert "view=unread" not in urls[0]
        assert "t=12345" in urls[0]


class TestBikerEeParser:
    def test_vtx1800_wtb_parsed(self) -> None:
        html = (FIXTURES / "O_ VTX1800 tagaamordid -.html").read_text(encoding="utf-8")
        url = "https://biker.ee/phpbb/viewtopic.php?f=90&t=56789"
        post = _ADAPTER._parse_topic_page(html, url)
        assert post is not None
        assert post.source == "biker_ee"
        assert "VTX1800" in post.raw_text
        assert "tagaamordid" in post.raw_text.lower() or "vtx1800" in post.raw_text.lower()
        assert post.lang_guess == "et"

    def test_suzuki_ls650_wtb_parsed(self) -> None:
        html = (FIXTURES / "O_ Suzuki LS650 Savage kraami -.html").read_text(encoding="utf-8")
        url = "https://biker.ee/phpbb/viewtopic.php?f=90&t=56790"
        post = _ADAPTER._parse_topic_page(html, url)
        assert post is not None
        assert "Suzuki" in post.raw_text or "LS650" in post.raw_text

    def test_discussion_thread_skipped(self) -> None:
        fname = "CBR 1000F käyntiongelma, auttakaa viisaammat! _ .ORG!.html"
        html = (FIXTURES / fname).read_text(encoding="utf-8")
        url = "https://biker.ee/phpbb/viewtopic.php?f=10&t=11111"
        # This fixture is a discussion thread without O:/M: prefix — should be skipped
        post = _ADAPTER._parse_topic_page(html, url)
        # Either returns None (no postbody found on this non-biker.ee page) or skips non-buy/sell
        # The fixture is from moottoripyora.org which uses different HTML structure
        assert post is None

    def test_source_post_id_from_url(self) -> None:
        html = (FIXTURES / "O_ VTX1800 tagaamordid -.html").read_text(encoding="utf-8")
        url = "https://biker.ee/phpbb/viewtopic.php?f=90&t=99001"
        post = _ADAPTER._parse_topic_page(html, url)
        assert post is not None
        assert post.source_post_id == "99001"

    def test_posted_at_parsed(self) -> None:
        html = (FIXTURES / "O_ VTX1800 tagaamordid -.html").read_text(encoding="utf-8")
        url = "https://biker.ee/phpbb/viewtopic.php?f=90&t=12345"
        post = _ADAPTER._parse_topic_page(html, url)
        assert post is not None
        assert post.posted_at is not None


class TestFetchHistory:
    def _patch_client(self, monkeypatch: pytest.MonkeyPatch, pages: dict[str, str]) -> None:
        monkeypatch.setattr(biker_ee.httpx, "Client", lambda **_: _FakeClient(pages))
        monkeypatch.setattr(biker_ee.time, "sleep", lambda *_: None)

    def test_stops_at_empty_page_and_filters_by_since(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pages = {
            "start=0": _index_html([1, 2]),
            "start=25": _index_html([3]),
            "start=50": _index_html([]),  # end of forum
            "t=1": _topic_html("O: front fender", "2024-06-01T00:00:00+00:00"),
            "t=2": _topic_html("O: rear shock", "2024-05-01T00:00:00+00:00"),
            "t=3": _topic_html("O: old part", "2020-01-01T00:00:00+00:00"),  # out of range
        }
        self._patch_client(monkeypatch, pages)

        posts = list(_ADAPTER.fetch_history(since=date(2024, 1, 1)))

        assert {p.source_post_id for p in posts} == {"1", "2"}
        assert all(p.historical for p in posts)

    def test_stale_page_limit_stops_pagination(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pages: dict[str, str] = {"t=1": _topic_html("O: front fender", "2024-06-01T00:00:00+00:00")}
        # First page has an in-range topic; every following page is non-empty but
        # entirely out-of-range, which should trip the stale-page limit rather than
        # looping until _HISTORY_MAX_PAGES.
        for page_num in range(biker_ee._HISTORY_STALE_PAGE_LIMIT + 3):
            start = page_num * biker_ee._HISTORY_PAGE_SIZE
            if page_num == 0:
                pages[f"start={start}"] = _index_html([1])
            else:
                topic_id = 100 + page_num
                pages[f"start={start}"] = _index_html([topic_id])
                pages[f"t={topic_id}"] = _topic_html(
                    "O: ancient part", "2010-01-01T00:00:00+00:00"
                )
        self._patch_client(monkeypatch, pages)

        posts = list(_ADAPTER.fetch_history(since=date(2024, 1, 1)))

        assert {p.source_post_id for p in posts} == {"1"}

    def test_same_topic_resurfacing_on_later_page_is_not_refetched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A bumped topic can appear on an earlier page fetch without
        # view=unread and resurface on a later page fetch with it (or vice
        # versa) — same topic id, different URL string. Must be counted once.
        pages = {
            "start=0": (
                '<html><body>'
                '<a class="topictitle" href="viewtopic.php?f=90&amp;t=1">topic</a>'
                '</body></html>'
            ),
            "start=25": (
                '<html><body>'
                '<a href="viewtopic.php?f=90&amp;t=1&amp;view=unread#unread">topic (bumped)</a>'
                '</body></html>'
            ),
            "start=50": _index_html([]),  # end of forum
            "t=1": _topic_html("O: front fender", "2024-06-01T00:00:00+00:00"),
        }
        self._patch_client(monkeypatch, pages)

        posts = list(_ADAPTER.fetch_history(since=date(2024, 1, 1)))

        assert len(posts) == 1
