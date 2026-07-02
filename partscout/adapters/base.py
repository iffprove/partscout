# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date

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

    def fetch_history(self, since: date) -> Iterator[RawPost]:
        """Paginate backward through historical posts, back to `since`.

        Only forum/WTB adapters implement this (Phase 1.5 backtest). Marketplace
        FS adapters keep this default — expired listings aren't retrievable, so
        only the current fetch_new() snapshot is usable for those sources.
        Must never raise on network errors — log and stop yielding instead.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support fetch_history")

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Stable identifier used in raw_posts.source."""
