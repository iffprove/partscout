# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import random
import re
import time

import httpx
from bs4 import BeautifulSoup, Tag

from partscout.adapters.base import SourceAdapter
from partscout.extraction.schemas import RawPost

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "PartScout/0.1 (+https://github.com/partscout; bot@partscout.example)"
)
_RATE_LIMIT_SECS = 5.0

# Sporthoj.com classifieds: FS ("Säljes") and WTB ("Köpes") live on separate index pages.
_LIST_URLS = (
    "https://www.sporthoj.com/annonser",
    "https://www.sporthoj.com/annonser/kopes",
)
_ITEM_URL_RE = re.compile(r"https://www\.sporthoj\.com/annonser/id/\d+")
_PRICE_RE = re.compile(r"([\d\s]+)\s*:-")


class SporthojAdapter(SourceAdapter):
    """Scrapes FS and WTB classifieds from sporthoj.com."""

    source_name = "sporthoj"

    def fetch_new(self) -> list[RawPost]:
        try:
            return self._scrape_index()
        except Exception:
            logger.exception("SporthojAdapter.fetch_new failed")
            return []

    # ------------------------------------------------------------------
    # Live scraping
    # ------------------------------------------------------------------

    def _scrape_index(self) -> list[RawPost]:
        listing_urls: list[str] = []
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=30,
        ) as client:
            for list_url in _LIST_URLS:
                resp = client.get(list_url)
                resp.raise_for_status()
                for url in self._parse_index_page(resp.text):
                    if url not in listing_urls:
                        listing_urls.append(url)

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
                    post = self._parse_listing_page(resp.text, url)
                    if post:
                        posts.append(post)
                except Exception:
                    logger.exception("Failed to fetch %s", url)
                finally:
                    time.sleep(_RATE_LIMIT_SECS + random.uniform(0, 2))
        return posts

    def _parse_index_page(self, html: str) -> list[str]:
        urls: list[str] = []
        for match in _ITEM_URL_RE.finditer(html):
            url = match.group(0)
            if url not in urls:
                urls.append(url)
        return urls

    # ------------------------------------------------------------------
    # HTML parsing (called directly in tests with fixture content)
    # ------------------------------------------------------------------

    def _parse_listing_page(self, html: str, url: str) -> RawPost | None:
        soup = BeautifulSoup(html, "lxml")

        title_tag = soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else ""

        info_heading = soup.find("h3", string="Annonsuppgifter")
        if not isinstance(info_heading, Tag):
            logger.warning("No Annonsuppgifter section found at %s", url)
            return None

        attributes = self._extract_attributes(info_heading)
        description = self._extract_description(info_heading)

        if not title and not description:
            logger.warning("No content found at %s", url)
            return None

        price_str = ""
        price_tag = soup.find("span", class_="buysell-price")
        if price_tag:
            price_match = _PRICE_RE.search(price_tag.get_text(strip=True))
            if price_match:
                amount = price_match.group(1).strip()
                # WTB ("Köpes") ads require a price field but have no real price;
                # sellers enter a nominal 0 or 1 as a placeholder.
                if amount and amount not in ("0", "1"):
                    price_str = f"{amount} SEK"

        parts: list[str] = []
        if title:
            parts.append(title)
        for label, value in attributes.items():
            if value:
                parts.append(f"{label}: {value}")
        if description:
            parts.append(description)
        if price_str:
            parts.append(f"Price: {price_str}")

        raw_text = " | ".join(parts)

        return RawPost(
            source=self.source_name,
            source_post_id=self._id_from_url(url),
            url=url,
            lang_guess="sv",
            posted_at=None,
            raw_text=raw_text,
            raw_html=html,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_attributes(self, info_heading: Tag) -> dict[str, str]:
        table = info_heading.find_next("table")
        attributes: dict[str, str] = {}
        if not isinstance(table, Tag):
            return attributes
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) == 2:
                attributes[tds[0].get_text(strip=True)] = tds[1].get_text(strip=True)
        return attributes

    def _extract_description(self, info_heading: Tag) -> str:
        container = info_heading.find_parent("div")
        if not isinstance(container, Tag):
            return ""
        p = container.find("p")
        return p.get_text(separator=" ", strip=True) if p else ""

    def _id_from_url(self, url: str) -> str:
        m = re.search(r"/id/(\d+)", url)
        return m.group(1) if m else url
