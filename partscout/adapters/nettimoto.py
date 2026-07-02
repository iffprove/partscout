# -*- coding: utf-8 -*-
from __future__ import annotations

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
_LIST_URL = (
    "https://www.nettivaraosa.com/en/moottoripyoran-varaosat-ja-tarvikkeet?so=1&lng=en"
)


class NettimotoAdapter(SourceAdapter):
    """Scrapes FS listings from nettivaraosa.com (Nettimoto spare-parts section)."""

    source_name = "nettimoto"

    def fetch_new(self) -> list[RawPost]:
        try:
            return self._scrape_index()
        except Exception:
            logger.exception("NettimotoAdapter.fetch_new failed")
            return []

    # ------------------------------------------------------------------
    # Live scraping
    # ------------------------------------------------------------------

    def _scrape_index(self) -> list[RawPost]:
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=30,
        ) as client:
            resp = client.get(_LIST_URL)
            resp.raise_for_status()
            listing_urls = self._parse_index_page(resp.text)

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
        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        for a in soup.select("a[href*='/moottoripyoran-varaosat-ja-tarvikkeet/']"):
            href = a.get("href", "")
            if re.search(r"/\d+$", href):
                full = href if href.startswith("http") else f"https://www.nettivaraosa.com{href}"
                if full not in urls:
                    urls.append(full)
        return urls

    # ------------------------------------------------------------------
    # HTML parsing (called directly in tests with fixture content)
    # ------------------------------------------------------------------

    def _parse_listing_page(self, html: str, url: str) -> RawPost | None:
        soup = BeautifulSoup(html, "lxml")

        data = self._extract_json_ld(soup)
        product_info = self._extract_product_info(html)

        if not data and not product_info:
            logger.warning("No structured data found at %s", url)
            return None

        name = (data or {}).get("name", "")
        if not name and product_info:
            name = product_info.get("productName", "")

        price_offer: dict[str, Any] = (data or {}).get("offers", {})
        price_str = str(price_offer.get("price", "")) if price_offer else ""
        currency = price_offer.get("priceCurrency", "") if price_offer else ""

        # seller address available if needed for country field in raw_text

        vehicle_brand = product_info.get("vehicleBrand", "") if product_info else ""
        vehicle_model = product_info.get("vehicleModel", "") if product_info else ""
        production_date = product_info.get("productionDate", "") if product_info else ""
        product_id = str(product_info.get("productID", "")) if product_info else ""

        meta_desc = ""
        meta_tag = soup.find("meta", {"name": "description"})
        if meta_tag:
            meta_desc = meta_tag.get("content", "")  # type: ignore[arg-type]

        parts: list[str] = []
        if vehicle_brand:
            parts.append(vehicle_brand)
        if vehicle_model:
            parts.append(vehicle_model)
        if production_date:
            parts.append(production_date)
        if name:
            parts.append(name)
        if price_str:
            parts.append(f"Price: {price_str} {currency}".strip())
        if meta_desc:
            parts.append(meta_desc)

        raw_text = " | ".join(parts)

        source_id = product_id or self._id_from_url(url)

        return RawPost(
            source=self.source_name,
            source_post_id=source_id,
            url=url,
            lang_guess="fi",
            posted_at=None,
            raw_text=raw_text,
            raw_html=html,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_json_ld(self, soup: BeautifulSoup) -> dict[str, Any] | None:
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict) and "Product" in str(data.get("@type", "")):
                    return data
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _extract_product_info(self, html: str) -> dict[str, Any] | None:
        m = re.search(r'"productInfo"\s*:\s*(\{[^}]+\})', html)
        if not m:
            return None
        try:
            return json.loads(m.group(1))  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            return None

    def _id_from_url(self, url: str) -> str:
        m = re.search(r"/(\d+)(?:\?.*)?$", url)
        return m.group(1) if m else url
