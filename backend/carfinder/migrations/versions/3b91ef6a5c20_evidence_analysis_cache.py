"""listing evidence and optional LLM cache

Revision ID: 3b91ef6a5c20
Revises: 2a5c71f0c19b
Create Date: 2026-09-29 21:10:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3b91ef6a5c20"
down_revision: Union[str, None] = "2a5c71f0c19b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "listing_analysis",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("semantic_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("llm_provider", sa.String(length=48), nullable=True),
        sa.Column("llm_model", sa.String(length=120), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["listing_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", name="uq_analysis_snapshot"),
    )
    op.create_index("ix_analysis_listing_created", "listing_analysis", ["listing_id", "created_at"])
    op.create_table(
        "listing_claims",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("claim_type", sa.String(length=80), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.String(length=24), server_default="claimed", nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["listing_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claims_listing_snapshot", "listing_claims", ["listing_id", "snapshot_id"])
    op.create_table(
        "llm_cache",
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=48), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("knowledge_version", sa.String(length=64), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("cache_key"),
    )


def downgrade() -> None:
    op.drop_table("llm_cache")
    op.drop_index("ix_claims_listing_snapshot", table_name="listing_claims")
    op.drop_table("listing_claims")
    op.drop_index("ix_analysis_listing_created", table_name="listing_analysis")
    op.drop_table("listing_analysis")
