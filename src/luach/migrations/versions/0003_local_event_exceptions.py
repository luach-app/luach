"""The local calendar's exceptions: one occurrence of a series deleted or changed on its own.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28

Google keeps a repeating event's cancelled and changed instances itself. The
local calendar (dev, a laptop, a demo) had nowhere to keep them, so deleting
one occurrence deleted the series and moving one moved them all. A row here is
one occurrence of a local_events series: `cancelled` (an EXDATE), or the fields
it has of its own in `changes_json`. It goes with its series.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "local_event_exceptions",
        sa.Column("series_id", sa.String(), nullable=False),
        sa.Column("occurrence", sa.String(), nullable=False),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.Column("changes_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["series_id"], ["local_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("series_id", "occurrence"),
    )


def downgrade() -> None:  # pragma: no cover - forward only
    raise NotImplementedError("luach migrates forward: a mistake is undone by the next revision")
