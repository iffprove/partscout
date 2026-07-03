# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime

import httpx
from bs4 import BeautifulSoup, Tag

from partscout.adapters.base import SourceAdapter
from partscout.extraction.schemas import RawPost

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "PartScout/0.1 (+https://github.com/partscout; bot@partscout.example)"
)
_RATE_LIMIT_SECS = 5.0
# Backtest pagination is a one-off overnight job — be extra polite to the small forum.
_HISTORY_RATE_LIMIT_SECS = 8.0

# biker.ee phpBB subforum for buying/selling motorcycle parts
_FORUM_URL = "https://biker.ee/phpbb/viewforum.php?f=90"
_BASE_URL = "https://biker.ee"
_HISTORY_PAGE_SIZE = 25  # phpBB default topics-per-page
_HISTORY_MAX_PAGES = 500  # hard safety cap
# phpBB sorts by last-reply time, so old threads get bumped — a handful of pages
# with nothing in range doesn't necessarily mean we've reached the forum's start.
# Stop once this many consecutive pages come back with zero in-range topics.
_HISTORY_STALE_PAGE_LIMIT = 8

# "O:" = ostmine (buying/WTB), "M:" = müümine (selling/FS)
_TITLE_KIND_RE = re.compile(r"^\s*(O|M)\s*:", re.IGNORECASE)


class BikerEeAdapter(SourceAdapter):
    """Scrapes WTB and FS posts from the biker.ee phpBB buy/sell subforum."""

    source_name = "biker_ee"

    def fetch_new(self) -> list[RawPost]:
        try:
            return self._scrape_forum()
        except Exception:
            logger.exception("BikerEeAdapter.fetch_new failed")
            return []

    def fetch_history(self, since: date) -> Iterator[RawPost]:
        try:
            yield from self._scrape_history(since)
        except Exception:
            logger.exception("BikerEeAdapter.fetch_history failed")
            return

    # ------------------------------------------------------------------
    # Live scraping
    # ------------------------------------------------------------------

    def _scrape_forum(self) -> list[RawPost]:
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=30,
        ) as client:
            resp = client.get(_FORUM_URL)
            resp.raise_for_status()
            topic_urls = self._parse_forum_index(resp.text)

        posts: list[RawPost] = []
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=30,
        ) as client:
            for url in topic_urls:
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                    post = self._parse_topic_page(resp.text, url)
                    if post:
                        posts.append(post)
                except Exception:
                    logger.exception("Failed to fetch %s", url)
                finally:
                    time.sleep(_RATE_LIMIT_SECS + random.uniform(0, 2))
        return posts

    def _scrape_history(self, since: date) -> Iterator[RawPost]:
        seen_topic_urls: set[str] = set()
        stale_pages = 0

        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=30,
        ) as client:
            for page_num in range(_HISTORY_MAX_PAGES):
                start = page_num * _HISTORY_PAGE_SIZE
                page_url = f"{_FORUM_URL}&start={start}"
                try:
                    resp = client.get(page_url)
                    resp.raise_for_status()
                except Exception:
                    logger.exception("Failed to fetch forum index page %s", page_url)
                    break
                finally:
                    time.sleep(_HISTORY_RATE_LIMIT_SECS + random.uniform(0, 3))

                topic_urls = self._parse_forum_index(resp.text)
                new_urls = [u for u in topic_urls if u not in seen_topic_urls]
                if not new_urls:
                    logger.info("No new topics at page %d — end of forum reached", page_num)
                    break
                seen_topic_urls.update(new_urls)

                page_had_in_range = False
                for url in new_urls:
                    try:
                        resp = client.get(url)
                        resp.raise_for_status()
                    except Exception:
                        logger.exception("Failed to fetch %s", url)
                        continue
                    finally:
                        time.sleep(_HISTORY_RATE_LIMIT_SECS + random.uniform(0, 3))

                    post = self._parse_topic_page(resp.text, url)
                    if post is None:
                        continue
                    if post.posted_at is not None and post.posted_at.date() < since:
                        continue
                    page_had_in_range = True
                    yield post.model_copy(update={"historical": True})

                if page_had_in_range:
                    stale_pages = 0
                else:
                    stale_pages += 1
                    if stale_pages >= _HISTORY_STALE_PAGE_LIMIT:
                        logger.info(
                            "%d consecutive pages with nothing newer than %s — stopping",
                            stale_pages,
                            since,
                        )
                        break

    def _parse_forum_index(self, html: str) -> list[str]:
        # The topic list renders several anchors per row (title, "jump to
        # unread", last-post permalink) that all point at the same topic but
        # don't share a URL string — e.g. "viewtopic.php?t=123" vs
        # "viewtopic.php?p=456#p456". Dedupe by topic id, keeping only
        # canonical t=-bearing links; p=-only permalinks are dropped since
        # the same topic's title link is always present alongside them.
        soup = BeautifulSoup(html, "lxml")
        seen_topic_ids: set[str] = set()
        urls: list[str] = []
        for a in soup.select("a.topictitle, a[href*='viewtopic.php']"):
            href = a.get("href", "")
            if not isinstance(href, str) or "viewtopic.php" not in href:
                continue
            m = re.search(r"[?&]t=(\d+)", href)
            if not m:
                continue
            topic_id = m.group(1)
            if topic_id in seen_topic_ids:
                continue
            seen_topic_ids.add(topic_id)
            full = href if href.startswith("http") else f"{_BASE_URL}/phpbb/{href}"
            urls.append(full)
        return urls

    # ------------------------------------------------------------------
    # HTML parsing (called directly in tests with fixture content)
    # ------------------------------------------------------------------

    def _parse_topic_page(self, html: str, url: str) -> RawPost | None:
        soup = BeautifulSoup(html, "lxml")

        postbody = soup.find("div", class_="postbody")
        if not isinstance(postbody, Tag):
            logger.warning("No postbody found at %s", url)
            return None

        title_tag = postbody.find("h3")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Skip discussion threads that aren't buy/sell
        if not _TITLE_KIND_RE.match(title):
            logger.debug("Skipping non-buy/sell topic: %s", title)
            return None

        content_tag = postbody.find("div", class_="content")
        body_text = content_tag.get_text(separator=" ", strip=True) if content_tag else ""

        time_tag = postbody.find("time")
        posted_at: datetime | None = None
        if isinstance(time_tag, Tag):
            dt_str = time_tag.get("datetime", "")
            try:
                posted_at = datetime.fromisoformat(str(dt_str)).astimezone(UTC)
            except (ValueError, TypeError):
                pass

        author_tag = postbody.find("strong")
        author = author_tag.get_text(strip=True) if author_tag else ""

        # Extract post ID from URL or page content
        source_id = self._post_id_from_url(url)

        raw_text = f"{title} | {body_text}"
        if author:
            raw_text += f" | Author: {author}"

        return RawPost(
            source=self.source_name,
            source_post_id=source_id,
            url=url,
            lang_guess="et",
            posted_at=posted_at,
            raw_text=raw_text,
            raw_html=html,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _post_id_from_url(self, url: str) -> str:
        # Extract topic id: viewtopic.php?f=90&t=12345
        m = re.search(r"[?&]t=(\d+)", url)
        if m:
            return m.group(1)
        # Fall back to the first post id found on the page
        m2 = re.search(r"post_content(\d+)", url)
        return m2.group(1) if m2 else url
