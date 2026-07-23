# -*- coding: utf-8 -*-
"""Entrypoint: polls all enabled sources, extracts, matches, and emails digests."""
from __future__ import annotations

import importlib
import logging
from datetime import UTC, datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv  # type: ignore[import-untyped]
from sqlalchemy.exc import IntegrityError

from partscout.config import (
    SOURCE_REGISTRY,
    SourceConfig,
    get_embedding_config,
    get_llm_config,
    get_smtp_config,
)
from partscout.db.session import get_session
from partscout.digest.emailer import send_digest
from partscout.extraction.extractor import Extractor
from partscout.extraction.llm import build_client
from partscout.extraction.schemas import RawPost
from partscout.matching.matcher import (
    generate_missing_embeddings,
    run_tier1_matching,
    run_tier2_matching,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _load_adapter(cfg: SourceConfig) -> object:
    module_path, class_name = cfg.adapter_class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(cfg)


def _build_embedding_client() -> object | None:
    emb_cfg = get_embedding_config()
    if not emb_cfg:
        return None
    from partscout.matching.embeddings import build_embedding_client
    return build_embedding_client(
        provider=emb_cfg.provider,
        model=emb_cfg.model,
        api_key=emb_cfg.api_key,
        base_url=emb_cfg.base_url,
    )


def _build_verifier() -> object | None:
    llm_cfg = get_llm_config()
    if not llm_cfg.api_key:
        return None
    from partscout.matching.verifier import MatchVerifier
    client = build_client(
        provider=llm_cfg.provider,
        model=llm_cfg.model,
        api_key=llm_cfg.api_key,
        base_url=llm_cfg.base_url,
        max_retries=llm_cfg.max_retries,
    )
    return MatchVerifier(client)


def poll_source(cfg: SourceConfig) -> None:
    logger.info("Polling source: %s", cfg.name)
    adapter = _load_adapter(cfg)
    posts: list[RawPost] = adapter.fetch_new()  # type: ignore[attr-defined]
    logger.info("Fetched %d posts from %s", len(posts), cfg.name)

    if not posts:
        return

    llm_cfg = get_llm_config()
    llm_client = build_client(
        provider=llm_cfg.provider,
        model=llm_cfg.model,
        api_key=llm_cfg.api_key,
        base_url=llm_cfg.base_url,
        max_retries=llm_cfg.max_retries,
    )
    extractor = Extractor(llm_client)

    with get_session() as session:
        from partscout.db.models import ListingRecord, RawPostRecord

        for post in posts:
            existing = (
                session.query(RawPostRecord)
                .filter_by(source=post.source, source_post_id=post.source_post_id)
                .first()
            )
            if existing:
                continue

            db_post = RawPostRecord(
                source=post.source,
                source_post_id=post.source_post_id,
                url=post.url,
                lang_guess=post.lang_guess,
                posted_at=post.posted_at,
                raw_text=post.raw_text,
                raw_html=post.raw_html,
                status="pending",
                historical=post.historical,
            )
            session.add(db_post)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                continue

            extracted = extractor.extract(post, country_hint=cfg.country)
            if extracted is None or extracted.kind == "other":
                db_post.status = (
                    "dropped" if extracted and extracted.kind == "other" else "failed"
                )
                continue

            attrs: dict[str, object] = {}
            if extracted.vehicle.make:
                attrs["make"] = extracted.vehicle.make
            if extracted.vehicle.model:
                attrs["model"] = extracted.vehicle.model
            if extracted.vehicle.year_from:
                attrs["year_from"] = extracted.vehicle.year_from
            if extracted.vehicle.year_to:
                attrs["year_to"] = extracted.vehicle.year_to

            listing = ListingRecord(
                raw_post_id=db_post.id,
                kind=extracted.kind,
                category="vehicle_parts",
                item_name_en=extracted.part.name_en,
                item_name_original=extracted.part.name_original,
                identifiers=extracted.part.part_numbers,
                attributes=attrs,
                condition=extracted.condition,
                price_value=extracted.price.value if extracted.price else None,
                price_currency=extracted.price.currency if extracted.price else None,
                country=extracted.location_country,
                confidence=extracted.confidence,
            )
            session.add(listing)
            db_post.status = "extracted"

        # Tier-1: exact part-number match
        t1 = run_tier1_matching(session)
        if t1:
            logger.info("%d new tier-1 matches from %s", len(t1), cfg.name)

        # Tier-2: embedding fuzzy + LLM verify (only if both clients available)
        emb_client = _build_embedding_client()
        if emb_client:
            generate_missing_embeddings(session, emb_client)
            verifier = _build_verifier()
            if verifier:
                t2 = run_tier2_matching(session, verifier)
                if t2:
                    logger.info("%d new tier-2 matches from %s", len(t2), cfg.name)
            else:
                logger.warning("No LLM configured — skipping tier-2 verification")
        else:
            logger.debug("No embedding client configured — skipping tier-2 matching")


def daily_digest() -> None:
    smtp_cfg = get_smtp_config()
    with get_session() as session:
        send_digest(session, smtp_cfg)


def main() -> None:
    load_dotenv()

    scheduler = BlockingScheduler(timezone=UTC)

    for source_cfg in SOURCE_REGISTRY:
        if not source_cfg.enabled:
            continue
        scheduler.add_job(
            poll_source,
            "interval",
            seconds=source_cfg.poll_interval_seconds,
            args=[source_cfg],
            id=f"poll_{source_cfg.name}",
            next_run_time=datetime.now(UTC),
        )

    scheduler.add_job(
        daily_digest,
        "cron",
        hour=7,
        minute=0,
        id="daily_digest",
    )

    enabled_count = sum(1 for s in SOURCE_REGISTRY if s.enabled)
    logger.info("Scheduler starting — %d sources enabled", enabled_count)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
