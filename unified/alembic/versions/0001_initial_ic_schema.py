"""Initial IC schema.

Revision ID: 0001_initial_ic_schema
Revises:
Create Date: 2026-03-28
"""

from __future__ import annotations

from alembic import op

from unified.canonical_store import metadata


revision = "0001_initial_ic_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    metadata.drop_all(bind=bind)

