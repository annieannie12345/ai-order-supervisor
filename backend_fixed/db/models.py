"""
db/models.py

SQLAlchemy 2.0 ORM models for the AI Order Supervisor Postgres read-model
mirror (see ARCHITECTURE.md §8).

Four tables:
    - supervisors : reusable agent configuration ("prompt + tools + policy")
    - runs        : one row per Temporal workflow execution (one per order_id)
    - events      : append-only inbound log (order events, instructions, signals)
    - actions     : append-only outbound/derived log (tool calls, memory
                    updates, wake schedules, final summaries)

Postgres is a *mirror*, not the source of truth for in-flight state — the
workflow (`OrderSupervisorWorkflow`) owns live state; activities write these
rows via `persist_snapshot`. Workflow code itself never touches this module
directly (that would break determinism); only activities do.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class RunStatus(str, enum.Enum):
    """Mirrors OrderSupervisorWorkflow.status (ARCHITECTURE.md §3)."""

    ACTIVE = "active"
    PAUSED = "paused"
    TERMINATED = "terminated"
    DONE = "done"


class EventType(str, enum.Enum):
    """Kinds of inbound records logged to `events` (ARCHITECTURE.md §8)."""

    ORDER_EVENT = "order_event"
    INSTRUCTION_ADDED = "instruction_added"
    INTERRUPT = "interrupt"
    RESUME = "resume"
    TERMINATE = "terminate"


class ActionType(str, enum.Enum):
    """Kinds of outbound/derived records logged to `actions` (ARCHITECTURE.md §8)."""

    TOOL_CALL = "tool_call"
    TOOL_FAILED = "tool_failed"
    MEMORY_UPDATED = "memory_updated"
    WAKE_SCHEDULED = "wake_scheduled"
    FINAL_SUMMARY = "final_summary"
    AGENT_ACTION = "agent_action"
    LIFECYCLE = "lifecycle"


# Shared native Postgres enum types (created once, reused as columns below).
run_status_enum = SAEnum(
    RunStatus,
    name="run_status",
    values_callable=lambda e: [member.value for member in e],
)
event_type_enum = SAEnum(
    EventType,
    name="event_type",
    values_callable=lambda e: [member.value for member in e],
)
action_type_enum = SAEnum(
    ActionType,
    name="action_type",
    values_callable=lambda e: [member.value for member in e],
)


# --------------------------------------------------------------------------
# Mixins
# --------------------------------------------------------------------------


class TimestampMixin:
    """created_at / updated_at columns, server-side defaults."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def _uuid_str() -> str:
    """Default factory for string-typed UUID primary keys."""
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Supervisor
# --------------------------------------------------------------------------


class Supervisor(TimestampMixin, Base):
    """
    A reusable agent configuration: base instruction, allowed tools, wake
    policy, and LLM/model settings. One Supervisor can back many Runs.
    """

    __tablename__ = "supervisors"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid_str
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_instruction: Mapped[str] = mapped_column(String, nullable=False)

    tools: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    wake_policy: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    # Trailing underscore avoids shadowing Pydantic's protected
    # `model_config` name at the schema layer; DB column is `model_config`.
    model_config_: Mapped[dict[str, Any]] = mapped_column(
        "model_config", JSONB, nullable=False, default=dict
    )

    runs: Mapped[list["Run"]] = relationship(
        "Run",
        back_populates="supervisor",
        cascade="save-update, merge",
        # NOTE: `passive_deletes` is a no-op (and misleading) here since the
        # FK uses `ondelete="RESTRICT"` (no DB-side cascade to defer to).
        # Removed per audit M4.
    )

    __table_args__ = (
        Index("ix_supervisors_name", "name"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Supervisor id={self.id!r} name={self.name!r}>"


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------


class Run(TimestampMixin, Base):
    """
    One row per Temporal workflow execution (`OrderSupervisorWorkflow`),
    keyed by `order_id`. Mirrors `RunState` (workflow query result) so that
    `GET /runs` list views never need to fan out to N running workflows.
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid_str
    )
    order_id: Mapped[str] = mapped_column(String(255), nullable=False)

    supervisor_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("supervisors.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Temporal workflow id, e.g. "order-supervisor-{order_id}" — unique,
    # gives idempotent "start if not running" semantics (ARCHITECTURE.md §1).
    workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[RunStatus] = mapped_column(
        run_status_enum, nullable=False, default=RunStatus.ACTIVE
    )
    next_wake_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    supervisor: Mapped["Supervisor"] = relationship(
        "Supervisor", back_populates="runs"
    )
    events: Mapped[list["Event"]] = relationship(
        "Event",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Event.ts",
    )
    actions: Mapped[list["Action"]] = relationship(
        "Action",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Action.ts",
    )

    __table_args__ = (
        UniqueConstraint("workflow_id", name="uq_runs_workflow_id"),
        UniqueConstraint("order_id", name="uq_runs_order_id"),
        # NOTE: the explicit Index on order_id was removed — the
        # UniqueConstraint above already creates an implicit unique index
        # covering that column, so this was a redundant duplicate index.
        Index("ix_runs_supervisor_id", "supervisor_id"),
        Index("ix_runs_status", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Run id={self.id!r} order_id={self.order_id!r} status={self.status!r}>"


# --------------------------------------------------------------------------
# Event  (append-only inbound log)
# --------------------------------------------------------------------------


class Event(Base):
    """
    Everything that came *in* to a run: order events, added instructions,
    and interrupt/resume/terminate signals. `important` is set by the
    `classify_event_importance` activity's verdict (null until classified).
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # NOTE: now uses the native `event_type_enum` Postgres enum (previously
    # declared above but never actually wired to this column, so EventType
    # provided no DB-level enforcement at all).
    type: Mapped[EventType] = mapped_column(event_type_enum, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    important: Mapped[Optional[bool]] = mapped_column(nullable=True)

    run: Mapped["Run"] = relationship("Run", back_populates="events")

    __table_args__ = (
        Index("ix_events_run_id_ts", "run_id", "ts"),
        Index("ix_events_type", "type"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Event id={self.id} run_id={self.run_id!r} type={self.type!r}>"


# --------------------------------------------------------------------------
# Action  (append-only outbound/derived log)
# --------------------------------------------------------------------------


class Action(Base):
    """
    Everything the agent did or decided: tool calls, memory rewrites, wake
    scheduling, and the final summary. "Current memory" and "final summary"
    are *derived* by querying the latest row of the relevant `type` rather
    than modeled as separate mutable tables (ARCHITECTURE.md §8).
    """

    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # NOTE: now uses the native `action_type_enum` Postgres enum (previously
    # declared above but never actually wired to this column, so ActionType
    # provided no DB-level enforcement at all).
    type: Mapped[ActionType] = mapped_column(action_type_enum, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    run: Mapped["Run"] = relationship("Run", back_populates="actions")

    __table_args__ = (
        # Fast "latest memory_updated / final_summary row for this run" lookups.
        Index("ix_actions_run_id_ts", "run_id", "ts"),
        Index("ix_actions_run_id_type_ts", "run_id", "type", "ts"),
        # NOTE: previously allowed a completely different literal set
        # ("agent_action", "closed", "terminated", "interrupted", "resumed",
        # "instruction_added", "terminate_requested", "tool:%") that didn't
        # match the ActionType enum at all — three of the five enum values
        # (tool_call, memory_updated, final_summary) were NOT permitted by
        # the old constraint and would have raised a Postgres CheckViolation
        # on insert. Now that `type` is backed by the native `action_type_enum`
        # Postgres enum above, Postgres itself already restricts `type` to
        # exactly the ActionType values, so this CheckConstraint is no longer
        # necessary and has been removed to avoid having two separate,
        # potentially-diverging sources of truth for the same vocabulary.
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Action id={self.id} run_id={self.run_id!r} type={self.type!r}>"
