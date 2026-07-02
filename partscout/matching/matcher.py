# -*- coding: utf-8 -*-
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from partscout.db.models import ListingRecord, MatchRecord
from partscout.matching.normalizer import (
    brands_compatible,
    normalize_identifiers,
    years_overlap,
)

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.80
TOP_K_CANDIDATES = 5


# ---------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------


def generate_missing_embeddings(
    session: Session,
    embedding_client: object,  # EmbeddingClient — avoid circular import at module level
) -> int:
    """Generate and store embeddings for listings that don't have one yet.

    Returns the number of listings updated.
    """
    from partscout.matching.embeddings import EmbeddingClient

    assert isinstance(embedding_client, EmbeddingClient)

    pending: list[ListingRecord] = (
        session.query(ListingRecord).filter(ListingRecord.embedding.is_(None)).all()
    )
    if not pending:
        return 0

    texts = [listing.item_name_en for listing in pending]
    try:
        vectors = embedding_client.embed(texts)
    except Exception:
        logger.exception("Embedding generation failed for %d listings", len(pending))
        return 0

    for listing, vec in zip(pending, vectors):
        listing.embedding = vec

    logger.info("Generated embeddings for %d listings", len(pending))
    return len(pending)


# ---------------------------------------------------------------------------
# Tier 1 — exact part-number match
# ---------------------------------------------------------------------------


def run_tier1_matching(session: Session) -> list[MatchRecord]:
    """Exact part-number match between all WTB and FS listings.

    Excludes same-source same-thread pairs and pairs already in matches table.
    """
    wtb_listings: list[ListingRecord] = (
        session.query(ListingRecord).filter(ListingRecord.kind == "wtb").all()
    )
    fs_listings: list[ListingRecord] = (
        session.query(ListingRecord).filter(ListingRecord.kind == "fs").all()
    )

    existing_pairs: set[tuple[int, int]] = {
        (m.wtb_id, m.fs_id)
        for m in session.query(MatchRecord.wtb_id, MatchRecord.fs_id).all()
    }

    new_matches: list[MatchRecord] = []

    for wtb in wtb_listings:
        wtb_ids = normalize_identifiers(list(wtb.identifiers or []))
        if not wtb_ids:
            continue
        for fs in fs_listings:
            if (wtb.id, fs.id) in existing_pairs:
                continue
            if _same_source_thread(wtb, fs):
                continue
            fs_ids = normalize_identifiers(list(fs.identifiers or []))
            if not fs_ids:
                continue
            if wtb_ids & fs_ids:
                logger.info(
                    "Tier-1 match: wtb=%d fs=%d parts=%s",
                    wtb.id,
                    fs.id,
                    wtb_ids & fs_ids,
                )
                match = MatchRecord(
                    wtb_id=wtb.id,
                    fs_id=fs.id,
                    tier="part_number",
                    score=1.0,
                    llm_verdict=None,
                    notified_at=None,
                )
                session.add(match)
                new_matches.append(match)
                existing_pairs.add((wtb.id, fs.id))

    return new_matches


# ---------------------------------------------------------------------------
# Tier 2 — fuzzy embedding + LLM verification
# ---------------------------------------------------------------------------


def run_tier2_matching(
    session: Session,
    verifier: object,  # MatchVerifier
    similarity_threshold: float = SIMILARITY_THRESHOLD,
    top_k: int = TOP_K_CANDIDATES,
) -> list[MatchRecord]:
    """Cosine-similarity fuzzy match with LLM verification.

    Skips WTB listings that already have a tier-1 match.
    Only considers FS listings with a stored embedding.
    Stores every verdict (including 'no') to prevent re-verification.
    """
    from partscout.matching.verifier import MatchVerifier

    assert isinstance(verifier, MatchVerifier)

    tier1_wtb_ids: set[int] = {
        m.wtb_id
        for m in session.query(MatchRecord.wtb_id)
        .filter(MatchRecord.tier == "part_number")
        .all()
    }
    existing_pairs: set[tuple[int, int]] = {
        (m.wtb_id, m.fs_id)
        for m in session.query(MatchRecord.wtb_id, MatchRecord.fs_id).all()
    }

    wtb_listings: list[ListingRecord] = (
        session.query(ListingRecord)
        .filter(
            ListingRecord.kind == "wtb",
            ListingRecord.embedding.isnot(None),
        )
        .all()
    )

    new_matches: list[MatchRecord] = []

    for wtb in wtb_listings:
        if wtb.id in tier1_wtb_ids:
            continue

        wtb_make = (wtb.attributes or {}).get("make")
        wtb_year_from = (wtb.attributes or {}).get("year_from")
        wtb_year_to = (wtb.attributes or {}).get("year_to")

        # pgvector cosine distance: lower = more similar
        # 1 - distance = cosine similarity
        distance_col = text(
            "1 - (embedding <=> :vec)"
        ).bindparams(vec=str(wtb.embedding))

        candidates: list[tuple[ListingRecord, float]] = (
            session.query(ListingRecord, distance_col.label("similarity"))
            .filter(
                ListingRecord.kind == "fs",
                ListingRecord.embedding.isnot(None),
                text("1 - (embedding <=> :vec) > :threshold").bindparams(
                    vec=str(wtb.embedding), threshold=similarity_threshold
                ),
            )
            .order_by(text("similarity DESC"))
            .limit(top_k)
            .all()
        )

        for fs, similarity in candidates:
            if (wtb.id, fs.id) in existing_pairs:
                continue
            if _same_source_thread(wtb, fs):
                continue

            fs_make = (fs.attributes or {}).get("make")
            if not brands_compatible(wtb_make, fs_make):
                continue

            fs_year_from = (fs.attributes or {}).get("year_from")
            fs_year_to = (fs.attributes or {}).get("year_to")
            if not years_overlap(wtb_year_from, wtb_year_to, fs_year_from, fs_year_to):
                continue

            wtb_text = wtb.raw_post.raw_text if wtb.raw_post else wtb.item_name_en
            fs_text = fs.raw_post.raw_text if fs.raw_post else fs.item_name_en
            verdict, _reason = verifier.verify(wtb_text, fs_text)

            logger.info(
                "Tier-2: wtb=%d fs=%d sim=%.3f verdict=%s",
                wtb.id,
                fs.id,
                similarity,
                verdict,
            )

            match = MatchRecord(
                wtb_id=wtb.id,
                fs_id=fs.id,
                tier="fuzzy",
                score=float(similarity),
                llm_verdict=verdict,
                notified_at=None,
            )
            session.add(match)
            new_matches.append(match)
            existing_pairs.add((wtb.id, fs.id))

    return new_matches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _same_source_thread(a: ListingRecord, b: ListingRecord) -> bool:
    return bool(a.raw_post_id and b.raw_post_id and a.raw_post_id == b.raw_post_id)
