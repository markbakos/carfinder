"""Create initial scrape run history."""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_scrape_runs"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="running", nullable=False),
        sa.Column("trigger", sa.String(length=24), server_default="cli", nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("profiles_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sources_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("listings_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("listings_new", sa.Integer(), server_default="0", nullable=False),
        sa.Column("listings_changed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("price_drops", sa.Integer(), server_default="0", nullable=False),
        sa.Column("listings_removed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("detail_requests", sa.Integer(), server_default="0", nullable=False),
        sa.Column("llm_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("llm_cache_hits", sa.Integer(), server_default="0", nullable=False),
        sa.Column("warning_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_table("scrape_runs")
