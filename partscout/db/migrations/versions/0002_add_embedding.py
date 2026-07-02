# -*- coding: utf-8 -*-
"""Add embedding column to listings and create HNSW index

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "listings",
        sa.Column("embedding", sa.Text, nullable=True),  # placeholder type
    )
    # Replace with proper vector type now that the extension exists
    op.execute("ALTER TABLE listings ALTER COLUMN embedding TYPE vector(1024) USING NULL")
    # HNSW index works on empty tables and requires no training data
    op.execute(
        "CREATE INDEX listings_embedding_hnsw "
        "ON listings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS listings_embedding_hnsw")
    op.drop_column("listings", "embedding")
