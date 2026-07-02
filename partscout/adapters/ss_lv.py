# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import random
import re
import time

import httpx
from bs4 import BeautifulSoup

from partscout.adapters.base import SourceAdapter
from partscout.extraction.schemas import RawPost

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "PartScout/0.1 (+https://github.com/partscout; bot@partscout.example)"
)
_RATE_LIMIT_SECS = 5.0

_BASE_URL = "https://www.ss.lv"
# "Other parts" catch-all under moto spare parts. ss.lv mixes FS ("Pārdod")
# and WTB ("Pērku") posts in the same category listing — kind is left to the
# LLM extractor rather than pre-filtered here.
_CATEGORY_URL = f"{_BASE_URL}/lv/transport/moto-transport/spare-parts/other-parts/"
_PRICE_RE = re.compile(r"(\d[\d\s]*)\s*€")


class SsLvAdapter(SourceAdapter):
    """Scrapes moto spare-parts listings (FS+WTB) from ss.lv."""

    source_name = "ss_lv"

    def fetch_new(self) -> list[RawPost]:
        try:
            return self._scrape_category()
        except Exception:
            logger.exception("SsLvAdapter.fetch_new failed")
            return []

    # ------------------------------------------------------------------
    # Live scraping
    # ------------------------------------------------------------------

    def _scrape_category(self) -> list[RawPost]:
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=30,
        ) as client:
            resp = client.get(_CATEGORY_URL)
            resp.raise_for_status()
            listing_urls = self._parse_category_page(resp.text)

        posts: list[RawPost] = []
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=30,
        ) as client:
            for url in listing_urls:
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                    post = self._parse_item_page(resp.text, url)
                    if post:
                        posts.append(post)
                except Exception:
                    logger.exception("Failed to fetch %s", url)
                finally:
                    time.sleep(_RATE_LIMIT_SECS + random.uniform(0, 2))
        return posts

    # ------------------------------------------------------------------
    # HTML parsing (called directly in tests with fixture content)
    # ------------------------------------------------------------------

    def _parse_category_page(self, page_html: str) -> list[str]:
        soup = BeautifulSoup(page_html, "lxml")
        urls: list[str] = []
        for a in soup.select("a[href*='/msg/']"):
            href = a.get("href", "")
            if not isinstance(href, str) or "/msg/" not in href:
                continue
            full = href if href.startswith("http") else f"{_BASE_URL}{href}"
            if full not in urls:
                urls.append(full)
        return urls

    def _parse_item_page(self, page_html: str, url: str) -> RawPost | None:
        soup = BeautifulSoup(page_html, "lxml")

        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
        # Strip the "SS.LV <breadcrumb> - Sludinājumi" wrapper the <title> adds.
        title = re.sub(r"^SS\.LV\s+", "", title)
        title = re.sub(r"\s*-\s*Sludin[āa]jumi\s*$", "", title)

        desc_tag = soup.find(id="msg_div_msg")
        description = desc_tag.get_text(separator=" ", strip=True) if desc_tag else ""

        if not title and not description:
            logger.warning("No content found at %s", url)
            return None

        price_match = _PRICE_RE.search(page_html)
        price = f"{price_match.group(1).strip()} EUR" if price_match else ""

        parts = [p for p in (title, description) if p]
        if price:
            parts.append(f"Price: {price}")

        return RawPost(
            source=self.source_name,
            source_post_id=self._id_from_url(url),
            url=url,
            lang_guess="lv",
            posted_at=None,
            raw_text=" | ".join(parts),
            raw_html=page_html,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _id_from_url(self, url: str) -> str:
        m = re.search(r"/([^/]+)\.html$", url)
        return m.group(1) if m else url
