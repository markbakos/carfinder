"""allow native-filter provider sources

Revision ID: 2a5c71f0c19b
Revises: 4fbe7604a7a8
Create Date: 2026-09-29 20:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2a5c71f0c19b"
down_revision: Union[str, None] = "4fbe7604a7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("provider_sources") as batch_op:
        batch_op.alter_column("search_url", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("provider_sources") as batch_op:
        batch_op.alter_column("search_url", existing_type=sa.Text(), nullable=False)
