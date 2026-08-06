"""Initial schema: supervisors, runs, events, actions.

Mirrors db/models.py exactly (ARCHITECTURE.md §8).

Revision ID: 0001
Revises:
Create Date: 2026-07-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


run_status_enum = ENUM(
    "active", "paused", "terminated", "done", name="run_status", create_type=False
)
event_type_enum = ENUM(
    "order_event",
    "instruction_added",
    "interrupt",
    "resume",
    "terminate",
    name="event_type",
    create_type=False,
)
action_type_enum = ENUM(
    "tool_call",
    "tool_failed",
    "memory_updated",
    "wake_scheduled",
    "final_summary",
    "agent_action",
    "lifecycle",
    name="action_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    ENUM("active", "paused", "terminated", "done", name="run_status").create(bind, checkfirst=True)
    ENUM(
        "order_event",
        "instruction_added",
        "interrupt",
        "resume",
        "terminate",
        name="event_type",
    ).create(bind, checkfirst=True)
    ENUM(
        "tool_call",
        "tool_failed",
        "memory_updated",
        "wake_scheduled",
        "final_summary",
        "agent_action",
        "lifecycle",
        name="action_type",
    ).create(bind, checkfirst=True)

    op.create_table(
        "supervisors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("base_instruction", sa.String(), nullable=False),
        sa.Column("tools", JSONB, nullable=False, server_default="[]"),
        sa.Column("wake_policy", JSONB, nullable=False, server_default="{}"),
        sa.Column("model_config", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_supervisors_name", "supervisors", ["name"])

    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(255), nullable=False),
        sa.Column(
            "supervisor_id",
            sa.String(36),
            sa.ForeignKey("supervisors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("workflow_id", sa.String(255), nullable=False),
        sa.Column(
            "status",
            run_status_enum,
            nullable=False,
            server_default="active",
        ),
        sa.Column("next_wake_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("workflow_id", name="uq_runs_workflow_id"),
        sa.UniqueConstraint("order_id", name="uq_runs_order_id"),
    )
    op.create_index("ix_runs_supervisor_id", "runs", ["supervisor_id"])
    op.create_index("ix_runs_status", "runs", ["status"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("type", event_type_enum, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("important", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_events_run_id_ts", "events", ["run_id", "ts"])
    op.create_index("ix_events_type", "events", ["type"])

    op.create_table(
        "actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("type", action_type_enum, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_actions_run_id_ts", "actions", ["run_id", "ts"])
    op.create_index(
        "ix_actions_run_id_type_ts", "actions", ["run_id", "type", "ts"]
    )


def downgrade() -> None:
    op.drop_table("actions")
    op.drop_table("events")
    op.drop_table("runs")
    op.drop_table("supervisors")

    bind = op.get_bind()
    action_type_enum.drop(bind, checkfirst=True)
    event_type_enum.drop(bind, checkfirst=True)
    run_status_enum.drop(bind, checkfirst=True)
