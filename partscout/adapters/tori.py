# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import html
import json
import logging
import random
import re
import time
from typing import Any

import httpx
from bs4 import BeautifulSoup

from partscout.adapters.base import SourceAdapter
from partscout.extraction.schemas import RawPost

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "PartScout/0.1 (+https://github.com/partscout; bot@partscout.example)"
)
_RATE_LIMIT_SECS = 5.0

# "Moottoripyörän varaosat" (motorcycle spare parts) category. Browsing the
# category directly (?category=2.90.20.10) is client-rendered — only the
# keyword-search variant of this endpoint is server-rendered, so we use that
# as the listing source instead.
_SEARCH_URL = (
    "https://www.tori.fi/recommerce/forsale/search"
    "?q=moottoripy%C3%B6r%C3%A4n+varaosat"
)
_QUERY_STATE_RE = re.compile(
    r'<script type="application/json" data-react-query-state[^>]*>(.*?)</script>',
    re.S,
)


class ToriAdapter(SourceAdapter):
    """Scrapes FS listings from tori.fi's motorcycle spare-parts search."""

    source_name = "tori"

    def fetch_new(self) -> list[RawPost]:
        try:
            return self._scrape_search()
        except Exception:
            logger.exception("ToriAdapter.fetch_new failed")
            return []

    # ------------------------------------------------------------------
    # Live scraping
    # ------------------------------------------------------------------

    def _scrape_search(self) -> list[RawPost]:
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=30,
        ) as client:
            resp = client.get(_SEARCH_URL)
            resp.raise_for_status()
            listing_urls = self._parse_search_page(resp.text)

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

    def _parse_search_page(self, page_html: str) -> list[str]:
        m = _QUERY_STATE_RE.search(page_html)
        if not m:
            logger.warning("No react-query-state payload found in search page")
            return []
        try:
            payload = json.loads(base64.b64decode(html.unescape(m.group(1))))
        except (ValueError, TypeError, UnicodeDecodeError):
            logger.exception("Failed to decode react-query-state payload")
            return []

        for query in payload.get("queries", []):
            data = query.get("state", {}).get("data")
            if isinstance(data, dict) and "docs" in data:
                urls: list[str] = []
                for doc in data["docs"]:
                    url = doc.get("canonical_url")
                    if url and url not in urls:
                        urls.append(url)
                return urls
        logger.warning("No search-results query found in react-query-state payload")
        return []

    def _parse_item_page(self, page_html: str, url: str) -> RawPost | None:
        soup = BeautifulSoup(page_html, "lxml")
        data = self._extract_json_ld_product(soup)
        if not data:
            logger.warning("No Product JSON-LD found at %s", url)
            return None

        name = data.get("name", "")
        description = data.get("description", "")

        offers = data.get("offers") or {}
        price = offers.get("price", "") if isinstance(offers, dict) else ""
        currency = offers.get("priceCurrency", "") if isinstance(offers, dict) else ""

        category = ""
        for prop in data.get("additionalProperty") or []:
            if prop.get("name") == "category":
                category = prop.get("value", "")

        parts = [p for p in (name, description) if p]
        if price:
            parts.append(f"Price: {price} {currency}".strip())
        if category:
            parts.append(f"Category: {category}")

        source_id = str(data.get("sku") or self._id_from_url(url))

        return RawPost(
            source=self.source_name,
            source_post_id=source_id,
            url=url,
            lang_guess="fi",
            posted_at=None,
            raw_text=" | ".join(parts),
            raw_html=page_html,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_json_ld_product(self, soup: BeautifulSoup) -> dict[str, Any] | None:
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "Product":
                return data
        return None

    def _id_from_url(self, url: str) -> str:
        m = re.search(r"/item/(\d+)", url)
        return m.group(1) if m else url
