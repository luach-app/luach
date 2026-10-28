"""Single sign-on is bound to the provider's subject after the first sign-in: oidc_links.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28

A sign-in used to find the member by the provider's email claim every time, so an
account at the provider that came to show a member's address (an address changed there)
signed in as that member. Now the first sign-in links the provider's subject to the
member; after that the subject decides, and another subject with that member's address
is refused. Nothing is linked by this migration: members who already sign in this way are
linked the next time they do, by their verified address, exactly as before.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "oidc_links",
        sa.Column("issuer", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("linked_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("issuer", "subject"),
    )
    op.create_index("ix_oidc_links_user_id", "oidc_links", ["user_id"])


def downgrade() -> None:  # pragma: no cover - forward only
    raise NotImplementedError("luach migrates forward: a mistake is undone by the next revision")
