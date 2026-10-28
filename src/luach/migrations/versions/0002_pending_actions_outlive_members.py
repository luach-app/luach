"""Held actions outlive the member who asked: pending_actions.user_id ON DELETE SET NULL.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28

The baseline gave pending_actions.user_id a foreign key with no ON DELETE, so
removing a member who had ever had an action held failed with a foreign-key
violation (a 500 on Members > Remove). Every other reference to a member either
goes with them (CASCADE) or, where the row is the household's, is kept as
nobody's (people.user_id, SET NULL). A held or decided action is the
household's record, so it is kept; a private one from that member's email scan
is then visible to nobody (agent/pending.py). The column was already nullable.
"""

from __future__ import annotations

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None

FK = "pending_actions_user_id_fkey"


def upgrade() -> None:
    # The baseline's constraint was unnamed in the models; Postgres named it this.
    op.drop_constraint(FK, "pending_actions", type_="foreignkey")
    op.create_foreign_key(FK, "pending_actions", "users", ["user_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:  # pragma: no cover - forward only
    raise NotImplementedError("luach migrates forward: a mistake is undone by the next revision")
