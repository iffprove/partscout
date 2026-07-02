# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod

from partscout.extraction.schemas import RawPost


class SourceAdapter(ABC):
    """One module per source; all implement this interface."""

    def __init__(self, config: object) -> None:
        self.config = config

    @abstractmethod
    def fetch_new(self) -> list[RawPost]:
        """Fetch posts/listings published since the last run.

        Must never raise on network errors — return [] and log instead.
        Must respect robots.txt and per-source rate limits.
        """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Stable identifier used in raw_posts.source."""
