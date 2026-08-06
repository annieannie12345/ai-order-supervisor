"""
api/routers/runs.py

FastAPI router for run lifecycle management: creating runs (which start
OrderSupervisorWorkflow executions), reading run/timeline state, and
signaling running workflows (events, instructions, interrupt/resume/
terminate).

Read endpoints prefer live workflow queries (source of truth) and fall
back to the Postgres mirror when the workflow is no longer open (done/
terminated executions, or transient query failures).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client, WorkflowHandle
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from api.deps import get_session, get_temporal_client
from db.models import Action, Event, Run, RunStatus, Supervisor
from schemas.action import TimelineEntryRead
from schemas.event import EventRead, EventSubmit
from schemas.instruction import InstructionSubmit
from schemas.run import RunCreate, RunRead, RunStateRead
from shared.constants import TASK_QUEUE
from shared.constants import workflow_id_for_order
from shared.dataclasses import (
    OrderContext,
    OrderEvent,
    RunState,
    SupervisorConfig,
    SupervisorInput,
    TimelineEntry,
)
from workflows.order_supervisor import OrderSupervisorWorkflow

logger = logging.getLogger("api.routers.runs")

router = APIRouter(prefix="/runs", tags=["runs"])

# NOTE: previously hardcoded here as a local literal ("order-supervisor"),
# which meant the API and worker could drift. Now imported directly from
# shared/constants.py, the single canonical source used by worker.py too.
WORKFLOW_TASK_QUEUE = TASK_QUEUE


async def _get_run_or_404(session: AsyncSession, run_id: str) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id!r} not found")
    return run


def _workflow_handle(temporal_client: Client, workflow_id: str) -> WorkflowHandle:
    return temporal_client.get_workflow_handle(workflow_id)


def _supervisor_config(supervisor: Supervisor) -> SupervisorConfig:
    return SupervisorConfig(
        id=supervisor.id,
        name=supervisor.name,
        base_instruction=supervisor.base_instruction,
        tools=list(supervisor.tools or []),
        wake_policy=dict(supervisor.wake_policy or {}),
        model_config=dict(supervisor.model_config_ or {}),
    )


async def _signal_or_404(handle: WorkflowHandle, signal_name: str, *args) -> None:
    """
    Send a signal to a workflow handle, translating "not found" / "already
    completed" RPC errors into a 404/409 rather than a raw 500.
    """
    try:
        await handle.signal(signal_name, *args)
    except RPCError as exc:
        message = str(exc).lower()
        if "not found" in message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow {handle.id!r} not found or not running",
            ) from exc
        logger.exception("Signal %r to workflow %r failed", signal_name, handle.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to signal workflow: {exc}",
        ) from exc


# --------------------------------------------------------------------------
# POST /runs
# --------------------------------------------------------------------------


@router.post("", response_model=RunRead, status_code=status.HTTP_201_CREATED)
async def create_run(
    body: RunCreate,
    session: AsyncSession = Depends(get_session),
    temporal_client: Client = Depends(get_temporal_client),
) -> Run:
    supervisor = await session.get(Supervisor, body.supervisor_id)
    if supervisor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Supervisor {body.supervisor_id!r} not found",
        )

    workflow_id = workflow_id_for_order(body.order_id)

    order_ctx = OrderContext(
        order_id=body.order_id,
        order_payload=body.order_payload,
        supervisor=_supervisor_config(supervisor),
    )
    workflow_input = SupervisorInput(
        order_ctx=order_ctx,
        initial_memory=body.initial_memory,
    )

    run = Run(
        id=str(uuid.uuid4()),
        order_id=body.order_id,
        supervisor_id=body.supervisor_id,
        workflow_id=workflow_id,
        status=RunStatus.ACTIVE,
        next_wake_at=None,
    )
    session.add(run)
    # NOTE: `get_session` (db/session.py) already commits on clean generator
    # exit, but we still commit explicitly *here* on purpose: we need the
    # run row committed (or the conflict raised) *before* we attempt to
    # start the workflow below, since the following except branches also
    # mutate `run.status` and commit again in response to workflow-start
    # failures. That is a real, intentional multi-commit flow driven by
    # branching, not a redundant double-commit.
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A run for order_id {body.order_id!r} already exists",
        ) from exc

    try:
        await temporal_client.start_workflow(
            OrderSupervisorWorkflow.run,
            workflow_input,
            id=workflow_id,
            task_queue=WORKFLOW_TASK_QUEUE,
        )
    except WorkflowAlreadyStartedError:
        run.status = RunStatus.ACTIVE
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A run for order_id {body.order_id!r} is already active "
            f"(workflow_id={workflow_id!r})",
        )
    except RPCError as exc:
        logger.exception("Failed to start workflow %r", workflow_id)
        run.status = RunStatus.TERMINATED
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to start workflow: {exc}",
        ) from exc
    await session.refresh(run)

    return run


# --------------------------------------------------------------------------
# GET /runs
# --------------------------------------------------------------------------


@router.get("", response_model=list[RunRead])
async def list_runs(
    session: AsyncSession = Depends(get_session),
    run_status: RunStatus | None = None,
    order_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Run]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    stmt = select(Run).order_by(Run.created_at.desc()).limit(limit).offset(offset)
    if run_status is not None:
        stmt = stmt.where(Run.status == run_status)
    if order_id is not None:
        stmt = stmt.where(Run.order_id == order_id)

    result = await session.execute(stmt)
    return list(result.scalars().all())


# --------------------------------------------------------------------------
# GET /runs/{run_id}
# --------------------------------------------------------------------------


@router.get("/{run_id}", response_model=RunStateRead)
async def get_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    temporal_client: Client = Depends(get_temporal_client),
) -> RunStateRead:
    run = await _get_run_or_404(session, run_id)

    # Prefer live workflow state when the run isn't already terminal in the
    # Postgres mirror; fall back to the mirror on query failure or once the
    # workflow execution is closed.
    if run.status not in (RunStatus.TERMINATED, RunStatus.DONE):
        handle = _workflow_handle(temporal_client, run.workflow_id)
        try:
            live_state: RunState = await handle.query(OrderSupervisorWorkflow.get_state)
            return RunStateRead(
                run_id=run.id,
                status=live_state.status,
                next_wake_at=live_state.next_wake_at,
                memory_summary=live_state.memory_summary,
            )
        except RPCError as exc:
            logger.warning(
                "Live query failed for workflow %r, falling back to DB mirror: %s",
                run.workflow_id,
                exc,
            )

    return RunStateRead(
        run_id=run.id,
        status=run.status.value,
        next_wake_at=run.next_wake_at,
        memory_summary=await _latest_memory_summary(session, run.id),
    )


async def _latest_memory_summary(session: AsyncSession, run_id: str) -> str:
    result = await session.execute(
        select(Action)
        .where(Action.run_id == run_id, Action.type == "memory_updated")
        .order_by(desc(Action.ts), desc(Action.id))
        .limit(1)
    )
    action = result.scalar_one_or_none()
    if action is None:
        return ""
    summary = (action.payload or {}).get("summary")
    return summary if isinstance(summary, str) else ""


# --------------------------------------------------------------------------
# GET /runs/{run_id}/timeline
# --------------------------------------------------------------------------


@router.get("/{run_id}/timeline", response_model=list[TimelineEntryRead])
async def get_run_timeline(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    temporal_client: Client = Depends(get_temporal_client),
) -> list[dict]:
    run = await _get_run_or_404(session, run_id)

    if run.status not in (RunStatus.TERMINATED, RunStatus.DONE):
        handle = _workflow_handle(temporal_client, run.workflow_id)
        try:
            entries: list[TimelineEntry] = await handle.query(
                OrderSupervisorWorkflow.get_timeline
            )
            return [
                {"ts": e.ts, "kind": e.kind, "payload": e.payload} for e in entries
            ]
        except RPCError as exc:
            logger.warning(
                "Live timeline query failed for workflow %r, falling back to DB: %s",
                run.workflow_id,
                exc,
            )

    # DB fallback: merge events + actions by timestamp. This only reflects
    # what's been persisted via persist_snapshot (i.e. may miss entries
    # from a continue_as_new run still buffered in workflow memory), but
    # is the best we can do once the execution is closed.
    #
    # NOTE: `persistence.py::_entry_to_row` always strips any "event:"
    # prefix before storing `Event.type`, so `Event.type` in the DB never
    # starts with "event:" — the re-add is unconditional, not a
    # conditional startswith check (which was dead code before).
    events_result = await session.execute(
        select(Event).where(Event.run_id == run.id).order_by(Event.ts)
    )
    actions_result = await session.execute(
        select(Action).where(Action.run_id == run.id).order_by(Action.ts)
    )

    merged = [
        {
            "ts": e.ts,
            "kind": f"event:{(e.payload or {}).get('event_type', e.type)}"
            if e.type == "order_event"
            else e.type,
            "payload": e.payload,
        }
        for e in events_result.scalars().all()
    ] + [
        {"ts": a.ts, "kind": a.type, "payload": a.payload}
        for a in actions_result.scalars().all()
    ]
    merged.sort(key=lambda entry: entry["ts"])
    return merged


# --------------------------------------------------------------------------
# POST /runs/{run_id}/events
# --------------------------------------------------------------------------


@router.post("/{run_id}/events", response_model=EventRead, status_code=status.HTTP_202_ACCEPTED)
async def submit_event(
    run_id: str,
    body: EventSubmit,
    session: AsyncSession = Depends(get_session),
    temporal_client: Client = Depends(get_temporal_client),
) -> EventRead:
    run = await _get_run_or_404(session, run_id)

    if run.status in (RunStatus.TERMINATED, RunStatus.DONE):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run {run_id!r} is {run.status.value} and cannot accept events",
        )

    handle = _workflow_handle(temporal_client, run.workflow_id)
    order_event = OrderEvent(type=body.type, payload=body.payload)
    await _signal_or_404(handle, "submit_event", order_event)

    # The workflow persists the canonical row asynchronously via
    # persist_snapshot; return an unpersisted echo so the caller gets an
    # immediate ack without waiting on the activity round-trip.
    #
    # Fix M5: previously used `run.updated_at` (the run row's last-update
    # time, which has nothing to do with this event) as `ts`. Use the
    # actual ingestion time instead; `id=-1` still signals "not yet
    # persisted" (documented below).
    return EventRead(
        id=-1,  # sentinel: real id/ts are assigned by persist_snapshot
        ts=datetime.now(timezone.utc),
        type=body.type,
        payload=body.payload,
        important=None,
    )


# --------------------------------------------------------------------------
# POST /runs/{run_id}/instructions
# --------------------------------------------------------------------------


@router.post("/{run_id}/instructions", status_code=status.HTTP_202_ACCEPTED)
async def add_instruction(
    run_id: str,
    body: InstructionSubmit,
    session: AsyncSession = Depends(get_session),
    temporal_client: Client = Depends(get_temporal_client),
) -> dict[str, str]:
    run = await _get_run_or_404(session, run_id)

    if run.status in (RunStatus.TERMINATED, RunStatus.DONE):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run {run_id!r} is {run.status.value} and cannot accept instructions",
        )

    handle = _workflow_handle(temporal_client, run.workflow_id)
    await _signal_or_404(handle, "add_instruction", body.instruction)

    return {"status": "accepted"}


# --------------------------------------------------------------------------
# POST /runs/{run_id}/interrupt
# --------------------------------------------------------------------------


@router.post("/{run_id}/interrupt", status_code=status.HTTP_202_ACCEPTED)
async def interrupt_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    temporal_client: Client = Depends(get_temporal_client),
) -> dict[str, str]:
    run = await _get_run_or_404(session, run_id)

    if run.status in (RunStatus.TERMINATED, RunStatus.DONE):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run {run_id!r} is {run.status.value} and cannot be interrupted",
        )

    handle = _workflow_handle(temporal_client, run.workflow_id)
    await _signal_or_404(handle, "interrupt")

    return {"status": "interrupt_requested"}


# --------------------------------------------------------------------------
# POST /runs/{run_id}/resume
# --------------------------------------------------------------------------


@router.post("/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    temporal_client: Client = Depends(get_temporal_client),
) -> dict[str, str]:
    run = await _get_run_or_404(session, run_id)

    if run.status in (RunStatus.TERMINATED, RunStatus.DONE):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run {run_id!r} is {run.status.value} and cannot be resumed",
        )

    handle = _workflow_handle(temporal_client, run.workflow_id)
    await _signal_or_404(handle, "resume")

    return {"status": "resume_requested"}


# --------------------------------------------------------------------------
# POST /runs/{run_id}/terminate
# --------------------------------------------------------------------------


@router.post("/{run_id}/terminate", status_code=status.HTTP_202_ACCEPTED)
async def terminate_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
    temporal_client: Client = Depends(get_temporal_client),
) -> dict[str, str]:
    run = await _get_run_or_404(session, run_id)

    if run.status in (RunStatus.TERMINATED, RunStatus.DONE):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run {run_id!r} is already {run.status.value}",
        )

    handle = _workflow_handle(temporal_client, run.workflow_id)
    await _signal_or_404(handle, "terminate")

    return {"status": "terminate_requested"}
