"""
activities/persistence.py

Persistence activity for the OrderSupervisorWorkflow: writes the Postgres
read-model mirror described in ARCHITECTURE.md §8.

Only one activity is exposed: `persist_snapshot`. It is called by the
workflow after every agent step (see order_supervisor.py::_persist_snapshot)
with exactly:

    persist_snapshot(order_id, status, next_wake_at, new_events, new_actions)

`new_events` / `new_actions` are the *incremental* lists of TimelineEntry
the workflow has accumulated since the last snapshot (already split by
kind — anything with kind starting "event:" goes to pending_event_entries,
everything else to pending_action_entries), so this activity only ever
inserts new rows plus updates the single `runs` row — it never re-derives
or replays history.

Notes
-----
- `run_id` here is the *order_id* used as the natural/business key for the
  `runs` row (see `runs.order_id` + unique constraint); `id` is a separate
  surrogate PK. `events.run_id` / `actions.run_id` reference `runs.id`, not
  the order_id string directly, to keep foreign keys stable even if a
  business key format ever changes.
- Workflow code must stay side-effect-free/deterministic, so all of this
  — including "which run row to update" — happens only inside this
  activity, never in workflow code.
- Precondition: `db.models.Run` declares non-nullable `supervisor_id` and
  `workflow_id` columns that this activity's signature has no way to
  supply. `persist_snapshot` therefore requires the `runs` row for this
  `order_id` to already exist (it's created by `POST /runs` ->
  `create_run`, which supplies those two columns) — this activity only
  ever *updates* that row, it never inserts a fresh one. If no such row
  exists yet (e.g. this activity ran before `create_run`'s insert
  committed, or the two paths ever diverge), we raise a clear
  `LookupError` instead of attempting a partial INSERT that would fail on
  a Postgres NOT NULL violation.
- Idempotency: `persist_snapshot` is not currently keyed to dedupe on
  Temporal activity retries (a retried call could double-insert events on
  connection failure right at commit time). For a POC this is coupled to
  TOOL_RETRY_POLICY-style capped retries and is called out explicitly per
  ARCHITECTURE.md §9's failure notes; a production system should carry an
  idempotency token (e.g. workflow run_id + a monotonic snapshot sequence
  number) and enforce a unique constraint on it.
- Models (`Run`, `Event`, `Action`) and session management now live in
  `db.models` / `db.session` respectively — this module no longer defines
  its own ORM classes, Base, engine, or session factory (see db/models.py,
  db/session.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func
from temporalio import activity

from db.models import Action, Event, Run, RunStatus
from db.session import async_session_factory
from shared.dataclasses import TimelineEntry


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #

async def _get_run_id_or_raise(
    session: AsyncSession,
    order_id: str,
    status: str,
    next_wake_at: datetime | None,
) -> str:
    """
    Update the `runs` row for this order_id (business key) and return its
    surrogate `id`, which events/actions rows use as their FK.

    NOTE: despite historically being named `_get_or_create_run_id`, this
    function never creates a row — it is strictly update-only (see below).
    Renamed to `_get_run_id_or_raise` so the name itself no longer implies
    upsert semantics that don't exist.

    This is intentionally update-only. `db.models.Run` requires
    non-nullable `supervisor_id` and `workflow_id`, neither of which this
    activity's signature receives, so it cannot safely construct a fresh
    row itself — that row must already have been created by
    `api/routers/runs.py::create_run` (which does have both values) before
    the workflow's first `persist_snapshot` call. If it isn't there yet,
    we fail loudly and immediately rather than attempting a partial
    INSERT that Postgres would reject with a NOT NULL violation anyway.
    """
    run_status = RunStatus(status) if not isinstance(status, RunStatus) else status

    stmt = (
        select(Run)
        .where(Run.order_id == order_id)
        .with_for_update()
    )
    result = await session.execute(stmt)
    run = result.scalar_one_or_none()

    if run is None:
        raise LookupError(
            f"persist_snapshot: no `runs` row found for order_id={order_id!r}. "
            "The run row must be created by POST /runs (create_run) — which "
            "supplies the required supervisor_id/workflow_id — before the "
            "workflow's first persist_snapshot call."
        )

    run.status = run_status
    run.next_wake_at = next_wake_at
    # NOTE: `run.updated_at` is intentionally not set here — `TimestampMixin`
    # already declares it with `onupdate=func.now()`, which fires
    # automatically on any UPDATE emitted for this row. Setting it manually
    # to a `func.now()` SQL construct was redundant and had the added
    # downside of leaving a non-`datetime` value on the in-memory attribute
    # until the next refresh.

    return run.id


# --------------------------------------------------------------------- #
# Action-kind normalization
# --------------------------------------------------------------------- #
#
# `TimelineEntry.kind` for actions is documented (shared/dataclasses.py) as
# one of: "agent_action" | "tool:*" | "tool_failed". `Action.type` is backed
# by the native Postgres `action_type_enum`, which only permits the
# `db.models.ActionType` values: tool_call | tool_failed | memory_updated |
# wake_scheduled | final_summary.
#
# Previously, non-Event kinds were written to `Action.type` verbatim
# (`row_type = entry.kind`), so a `"tool:send_customer_message"` or
# `"agent_action"` entry would pass Python-side validation and only fail at
# INSERT time with an opaque `InvalidTextRepresentation` from Postgres. This
# mapping makes the translation explicit and fails fast, in Python, with a
# clear error identifying the offending kind — instead of surfacing as a
# raw DB error mid-transaction.
#
# `db.models.ActionType` now also declares `AGENT_ACTION` and `LIFECYCLE`
# members specifically to cover the bare kinds the workflow emits on every
# step ("agent_action") and for control-flow bookkeeping ("closed",
# "terminated", "instruction_added", "interrupted", "resumed",
# "terminate_requested") — see the exact-map below.
_ACTION_KIND_PREFIX_MAP: dict[str, str] = {
    "tool:": "tool_call",
}
_ACTION_KIND_EXACT_MAP: dict[str, str] = {
    "tool_failed": "tool_failed",
    "memory_updated": "memory_updated",
    "wake_scheduled": "wake_scheduled",
    "final_summary": "final_summary",
    # Fix C1: the workflow (workflows/order_supervisor.py) actually emits
    # these additional bare kinds via `_append_timeline`/signal handlers.
    # Every one of them previously fell through to the `raise ValueError`
    # below, and since "agent_action" fires on every single agent step
    # (including workflow_start), the very first persist_snapshot call of
    # every run was guaranteed to fail.
    "agent_action": "agent_action",
    "closed": "lifecycle",
    "terminated": "lifecycle",
    "persistence_failed": "lifecycle",
}


def _normalize_action_kind(kind: str) -> str:
    if kind in _ACTION_KIND_EXACT_MAP:
        return _ACTION_KIND_EXACT_MAP[kind]
    for prefix, action_type in _ACTION_KIND_PREFIX_MAP.items():
        if kind.startswith(prefix):
            return action_type
    raise ValueError(
        f"persist_snapshot: don't know how to map TimelineEntry.kind={kind!r} "
        "to a db.models.ActionType. Known kinds: exact="
        f"{sorted(_ACTION_KIND_EXACT_MAP)}, prefixes="
        f"{sorted(_ACTION_KIND_PREFIX_MAP)}."
    )


def _entry_to_row(entry: TimelineEntry, run_id: str, model: type[Event] | type[Action]):
    payload = entry.payload
    important: bool | None = None

    if model is Event:
        if entry.kind.startswith("event:"):
            business_type = entry.kind.removeprefix("event:")
            row_type = "order_event"
            important = payload.get("important")
            if important is not None:
                important = bool(important)
            inner_payload = dict(payload.get("payload", payload) or {})
            payload = {"event_type": business_type, **inner_payload}
        else:
            row_type_map = {
                "instruction_added": "instruction_added",
                "interrupted": "interrupt",
                "resumed": "resume",
                "terminate_requested": "terminate",
            }
            row_type = row_type_map[entry.kind]
    else:
        row_type = _normalize_action_kind(entry.kind)

    kwargs: dict[str, Any] = {
        "run_id": run_id,
        "ts": entry.ts,
        "type": row_type,
        "payload": payload,
    }
    if model is Event:
        kwargs["important"] = important
    return model(**kwargs)


# --------------------------------------------------------------------- #
# Activity
# --------------------------------------------------------------------- #

@activity.defn
async def persist_snapshot(
    order_id: str,
    status: str,
    next_wake_at: datetime | None,
    new_events: list[TimelineEntry],
    new_actions: list[TimelineEntry],
) -> dict[str, Any]:
    """
    Update the `runs` row for this order and insert any new `events` /
    `actions` rows accumulated since the last snapshot.

    Called by the workflow after every agent step and once more on
    continue_as_new / termination, per order_supervisor.py's
    `_persist_snapshot`.
    """
    async with async_session_factory() as session:
        async with session.begin():
            run_id = await _get_run_id_or_raise(session, order_id, status, next_wake_at)

            if new_events:
                session.add_all(_entry_to_row(e, run_id, Event) for e in new_events)
            if new_actions:
                session.add_all(_entry_to_row(a, run_id, Action) for a in new_actions)

        # session.begin() commits on clean exit; re-select for a fresh count
        # only if useful for logging/observability.
        result = await session.execute(select(func.count()).select_from(Event).where(Event.run_id == run_id))
        total_events = result.scalar_one()

    activity.logger.info(
        "Persisted snapshot for order %s: status=%s events+=%d actions+=%d total_events=%d",
        order_id,
        status,
        len(new_events),
        len(new_actions),
        total_events,
    )

    return {
        "run_id": run_id,
        "order_id": order_id,
        "status": status,
        "events_written": len(new_events),
        "actions_written": len(new_actions),
    }
