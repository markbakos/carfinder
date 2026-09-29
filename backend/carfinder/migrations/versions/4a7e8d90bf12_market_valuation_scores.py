"""market valuation and explainable scores

Revision ID: 4a7e8d90bf12
Revises: 3b91ef6a5c20
Create Date: 2026-09-29 22:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4a7e8d90bf12"
down_revision: Union[str, None] = "3b91ef6a5c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("profile_listing_matches") as batch_op:
        batch_op.add_column(sa.Column("rank_score", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("profile_fit_explanation_json", sa.JSON(), nullable=True))
    op.create_table(
        "listing_valuations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("median_amount", sa.Integer(), nullable=True),
        sa.Column("lower_amount", sa.Integer(), nullable=True),
        sa.Column("upper_amount", sa.Integer(), nullable=True),
        sa.Column("difference_pct", sa.Float(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("excluded_outliers", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.String(length=24), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["listing_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", name="uq_valuation_snapshot"),
    )
    op.create_index("ix_valuations_listing_computed", "listing_valuations", ["listing_id", "computed_at"])
    op.create_table(
        "listing_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("coverage_pct", sa.Integer(), nullable=False),
        sa.Column("dimensions_json", sa.JSON(), nullable=False),
        sa.Column("explanation_json", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["listing_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", name="uq_score_snapshot"),
    )
    op.create_index("ix_scores_listing_computed", "listing_scores", ["listing_id", "computed_at"])


def downgrade() -> None:
    op.drop_index("ix_scores_listing_computed", table_name="listing_scores")
    op.drop_table("listing_scores")
    op.drop_index("ix_valuations_listing_computed", table_name="listing_valuations")
    op.drop_table("listing_valuations")
    with op.batch_alter_table("profile_listing_matches") as batch_op:
        batch_op.drop_column("profile_fit_explanation_json")
        batch_op.drop_column("rank_score")
