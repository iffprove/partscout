# -*- coding: utf-8 -*-
"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_posts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_post_id", sa.String(256), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("lang_guess", sa.String(8), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("raw_html", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.UniqueConstraint("source", "source_post_id", name="uq_raw_posts_source_id"),
        sa.CheckConstraint(
            "status IN ('pending','extracted','failed','dropped')",
            name="ck_raw_posts_status",
        ),
    )

    op.create_table(
        "listings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "raw_post_id", sa.Integer, sa.ForeignKey("raw_posts.id"), nullable=False
        ),
        sa.Column("kind", sa.String(3), nullable=False),
        sa.Column(
            "category", sa.String(64), nullable=False, server_default="vehicle_parts"
        ),
        sa.Column("item_name_en", sa.Text, nullable=False),
        sa.Column("item_name_original", sa.Text, nullable=False),
        sa.Column(
            "identifiers",
            ARRAY(sa.Text),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("attributes", JSONB, nullable=False, server_default="{}"),
        sa.Column("condition", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("price_value", sa.Numeric(10, 2), nullable=True),
        sa.Column("price_currency", sa.String(3), nullable=True),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.CheckConstraint("kind IN ('wtb','fs')", name="ck_listings_kind"),
        sa.CheckConstraint(
            "condition IN ('used','new','any','unknown')", name="ck_listings_condition"
        ),
    )

    op.create_table(
        "matches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "wtb_id", sa.Integer, sa.ForeignKey("listings.id"), nullable=False
        ),
        sa.Column(
            "fs_id", sa.Integer, sa.ForeignKey("listings.id"), nullable=False
        ),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("llm_verdict", sa.String(8), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("wtb_id", "fs_id", name="uq_matches_pair"),
        sa.CheckConstraint("tier IN ('part_number','fuzzy')", name="ck_matches_tier"),
        sa.CheckConstraint(
            "llm_verdict IS NULL OR llm_verdict IN ('match','likely','no')",
            name="ck_matches_verdict",
        ),
    )


def downgrade() -> None:
    op.drop_table("matches")
    op.drop_table("listings")
    op.drop_table("raw_posts")
