# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RawPostRecord(Base):
    __tablename__ = "raw_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_post_id: Mapped[str] = mapped_column(String(256), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    lang_guess: Mapped[str | None] = mapped_column(String(8), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    historical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("source", "source_post_id", name="uq_raw_posts_source_id"),
        CheckConstraint(
            "status IN ('pending','extracted','failed','dropped')", name="ck_raw_posts_status"
        ),
    )

    listings: Mapped[list[ListingRecord]] = relationship(
        "ListingRecord", back_populates="raw_post"
    )


class ListingRecord(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("raw_posts.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(3), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="vehicle_parts")
    item_name_en: Mapped[str] = mapped_column(Text, nullable=False)
    item_name_original: Mapped[str] = mapped_column(Text, nullable=False)
    identifiers: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    condition: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    price_value: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (
        CheckConstraint("kind IN ('wtb','fs')", name="ck_listings_kind"),
        CheckConstraint(
            "condition IN ('used','new','any','unknown')", name="ck_listings_condition"
        ),
    )

    raw_post: Mapped[RawPostRecord] = relationship("RawPostRecord", back_populates="listings")
    wtb_matches: Mapped[list[MatchRecord]] = relationship(
        "MatchRecord", foreign_keys="MatchRecord.wtb_id", back_populates="wtb_listing"
    )
    fs_matches: Mapped[list[MatchRecord]] = relationship(
        "MatchRecord", foreign_keys="MatchRecord.fs_id", back_populates="fs_listing"
    )


class MatchRecord(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wtb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("listings.id"), nullable=False
    )
    fs_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("listings.id"), nullable=False
    )
    tier: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    llm_verdict: Mapped[str | None] = mapped_column(String(8), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("wtb_id", "fs_id", name="uq_matches_pair"),
        CheckConstraint("tier IN ('part_number','fuzzy')", name="ck_matches_tier"),
        CheckConstraint(
            "llm_verdict IS NULL OR llm_verdict IN ('match','likely','no')",
            name="ck_matches_verdict",
        ),
    )

    wtb_listing: Mapped[ListingRecord] = relationship(
        "ListingRecord", foreign_keys=[wtb_id], back_populates="wtb_matches"
    )
    fs_listing: Mapped[ListingRecord] = relationship(
        "ListingRecord", foreign_keys=[fs_id], back_populates="fs_matches"
    )
