"""Each member's calendar subscription link: calendar_feeds.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28

A member may publish the household's events to their phone's own calendar app through
a secret link (luach.feed). One row per member who has turned it on; only the link's
SHA-256 is stored, and the row goes when the member does.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_feeds",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_read", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("token_hash"),
    )


def downgrade() -> None:  # pragma: no cover - forward only
    raise NotImplementedError("luach migrates forward: a mistake is undone by the next revision")
