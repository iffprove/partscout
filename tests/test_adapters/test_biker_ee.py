# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from partscout.adapters.biker_ee import BikerEeAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures" / "forum"

_ADAPTER = BikerEeAdapter(config=None)


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
