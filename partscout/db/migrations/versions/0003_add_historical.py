# -*- coding: utf-8 -*-
"""Add historical flag to raw_posts (Phase 1.5 backtest)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raw_posts",
        sa.Column("historical", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("raw_posts", "historical")
