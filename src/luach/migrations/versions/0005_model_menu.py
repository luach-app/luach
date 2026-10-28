"""The model menu lives in the database: menu_models and model_trials.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28

The menu was LUACH_MODELS, fixed at deploy time: changing, adding or repairing
a model needed a redeploy, and a model its provider had retired failed every
turn for days with nothing noticing. Now the owner manages it in the app, and
LUACH_MODELS only seeds an empty table (luach.model_menu.seed). model_trials
keeps each "Try it" run's score.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "menu_models",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("about", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("local", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("meta_json", sa.Text(), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("unhealthy_since", sa.DateTime(), nullable=True),
        sa.Column("unhealthy_reason", sa.Text(), nullable=False),
        sa.Column("last_ok_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "model_trials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("done", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_trials_model_id", "model_trials", ["model_id"])


def downgrade() -> None:  # pragma: no cover - forward only
    raise NotImplementedError("luach migrates forward: a mistake is undone by the next revision")
