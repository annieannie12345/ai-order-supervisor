"""
OrderSupervisorWorkflow — Temporal workflow definition.

Owns the full lifecycle of a single order-supervision run:
  * runs an initial agent step on start
  * accepts inbound order events and ad-hoc instructions via signals
  * classifies incoming events for importance before waking the agent
  * sleeps until either a signal arrives or the agent's requested wake time
    elapses
  * executes any tool calls the agent decides on
  * persists an incremental snapshot (new timeline entries + run status)
    after every agent step
  * continues-as-new once the in-memory timeline grows past the configured
    threshold, to keep workflow history bounded
  * supports interrupt/resume/terminate control signals
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Callable, Coroutine

from temporalio import workflow
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from activities import agent as agent_activities
    from activities import persistence as persistence_activities
    from activities import tools as tool_activities
    from shared.constants import (
        CONTINUE_AS_NEW_THRESHOLD,
        TERMINAL_STATUSES,
        TIMELINE_TRUNCATION_LENGTH,
    )
    from shared.dataclasses import (
        AgentStepInput,
        AgentStepResult,
        ClassifyInput,
        ClassifyResult,
        OrderContext,
        OrderEvent,
        RunState,
        SupervisorInput,
        TimelineEntry,
        ToolCall,
    )
    from shared.retry_policies import DEFAULT_RETRY_POLICY, TOOL_RETRY_POLICY


CLASSIFY_ACTIVITY_TIMEOUT = timedelta(seconds=30)
AGENT_STEP_ACTIVITY_TIMEOUT = timedelta(seconds=120)
TOOL_ACTIVITY_TIMEOUT = timedelta(seconds=30)
PERSIST_ACTIVITY_TIMEOUT = timedelta(seconds=30)
INBOUND_EVENT_KINDS = {
    "instruction_added",
    "interrupted",
    "resumed",
    "terminate_requested",
}


@workflow.defn
class OrderSupervisorWorkflow:
    """Long-running, event-driven supervisor for a single order."""

    def __init__(self) -> None:
        # Core state
        self._order_ctx: OrderContext | None = None
        self._memory_summary: str = ""
        self._status: str = "active"
        self._next_wake_at: Any = None  # datetime | None

        # Timeline (local, reset on each continue_as_new run)
        self._timeline: list[TimelineEntry] = []
        self._pending_events: list[OrderEvent] = []
        self._pending_event_entries: list[TimelineEntry] = []
        self._pending_action_entries: list[TimelineEntry] = []

        # Instruction / wake bookkeeping
        self._extra_instructions: list[str] = []
        self._wake_requested: bool = False
        self._wake_reason: str | None = None
        self._terminate_requested: bool = False

        # Tool-name -> activity dispatch table
        self._tool_activity_map: dict[str, Callable[..., Coroutine[Any, Any, Any]]] = {
            "send_customer_message": tool_activities.send_customer_message,
            "create_internal_note": tool_activities.create_internal_note,
            "escalate_issue": tool_activities.escalate_issue,
            "mark_for_review": tool_activities.mark_for_review,
            "schedule_next_wakeup": tool_activities.schedule_next_wakeup,
            "close_workflow": tool_activities.close_workflow,
        }

    # ------------------------------------------------------------------ #
    # Main entrypoint
    # ------------------------------------------------------------------ #

    @workflow.run
    async def run(self, input: SupervisorInput) -> None:
        self._order_ctx = input.order_ctx
        self._memory_summary = input.initial_memory or ""
        self._status = input.initial_status
        self._timeline = list(input.initial_timeline)
        self._extra_instructions = list(input.initial_extra_instructions)
        self._next_wake_at = input.initial_next_wake_at

        # Fresh execution only. Continue-as-new carries a small recent
        # timeline so the agent keeps situational context after rollover.
        if not self._timeline:
            await self._run_agent("workflow_start")
        else:
            await self._run_agent("continued_execution")

        while self._status not in TERMINAL_STATUSES:
            if self._terminate_requested:
                await self._finalize_termination()
                break

            if self._status == "paused":
                # While paused, only resume/terminate signals matter.
                await workflow.wait_condition(
                    lambda: self._status != "paused" or self._terminate_requested
                )
                continue

            wait_seconds = self._seconds_until_wake()
            try:
                await workflow.wait_condition(
                    lambda: (
                        bool(self._pending_events)
                        or
                        self._wake_requested
                        or self._terminate_requested
                        or self._status != "active"
                    ),
                    timeout=timedelta(seconds=wait_seconds)
                    if wait_seconds is not None
                    else None,
                )
            except asyncio.TimeoutError:
                # Scheduled wake time elapsed with no signal — fall through
                # and run a scheduled_wakeup step below.
                pass

            if self._terminate_requested:
                await self._finalize_termination()
                break

            if self._status != "active":
                # e.g. interrupted while we were waiting; loop back around
                # to the paused branch.
                continue

            events_were_drained = False
            important_event_seen = False
            if self._pending_events:
                events_were_drained = True
                important_event_seen = await self._drain_pending_events()

            if self._wake_requested or important_event_seen:
                reason = self._wake_reason or "signal"
                self._wake_requested = False
                self._wake_reason = None
                await self._run_agent(reason)
            elif self._next_wake_at is not None and workflow.now() >= self._next_wake_at:
                await self._run_agent("scheduled_wakeup")
            elif events_were_drained:
                await self._persist_snapshot()

            if (
                self._status not in TERMINAL_STATUSES
                and len(self._timeline) >= CONTINUE_AS_NEW_THRESHOLD
                and workflow.all_handlers_finished()
            ):
                if await self._persist_snapshot():
                    workflow.continue_as_new(self._carryover_input())
                    return

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _run_agent(
        self,
        reason: str,
        terminal_status: str = "done",
        close_reason: str = "agent_requested",
    ) -> None:
        assert self._order_ctx is not None

        step_input = AgentStepInput(
            order_ctx=self._order_ctx,
            reason=reason,
            memory_summary=self._memory_summary,
            recent_timeline=self._timeline[-TIMELINE_TRUNCATION_LENGTH:],
            extra_instructions=list(self._extra_instructions),
            available_tools=self._order_ctx.supervisor.tools,
        )

        activity_fn = (
            agent_activities.generate_final_summary
            if reason == "final_summary"
            else agent_activities.run_agent_step
        )

        try:
            result: AgentStepResult = await workflow.execute_activity(
                activity_fn,
                step_input,
                start_to_close_timeout=AGENT_STEP_ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
        except ActivityError as exc:
            workflow.logger.exception("agent activity failed after retries")
            self._status = "paused"
            self._next_wake_at = None
            self._append_timeline(
                "agent_action",
                {
                    "reason": reason,
                    "error": str(exc),
                    "paused_for_human_review": True,
                },
            )
            await self._persist_snapshot()
            return

        self._memory_summary = result.updated_memory_summary
        self._extra_instructions.clear()

        self._append_timeline(
            "agent_action",
            {
                "reason": reason,
                "actions_taken": result.actions_taken,
                "forced": result.forced,
            },
        )
        self._append_timeline("memory_updated", {"summary": self._memory_summary})
        if reason == "final_summary":
            self._append_timeline(
                "final_summary",
                {
                    "summary": self._memory_summary,
                    "actions_taken": result.actions_taken,
                    "forced": result.forced,
                },
            )

        wake_scheduled_by_tool = False
        for tool_call in result.tool_calls:
            wake_scheduled_by_tool = (
                await self._execute_tool_call(tool_call)
                or wake_scheduled_by_tool
            )

        if result.next_wake_at is not None and not result.close_workflow:
            self._next_wake_at = result.next_wake_at
            self._append_timeline(
                "wake_scheduled",
                {"next_wake_at": result.next_wake_at.isoformat()},
            )
        elif result.close_workflow:
            self._next_wake_at = None
        elif not wake_scheduled_by_tool:
            self._next_wake_at = None

        await self._persist_snapshot()

        if result.close_workflow:
            if reason == "final_summary":
                self._status = terminal_status
                timeline_kind = "terminated" if terminal_status == "terminated" else "closed"
                self._append_timeline(timeline_kind, {"reason": close_reason})
                await self._persist_snapshot()
            else:
                # Give the agent one more pass to produce a final wrap-up
                # (summary message, closing note, etc.) before terminating.
                await self._run_agent("final_summary")

    async def _drain_pending_events(self) -> bool:
        assert self._order_ctx is not None

        events, self._pending_events = self._pending_events, []
        important_event_seen = False

        for event in events:
            try:
                classify_result: ClassifyResult = await workflow.execute_activity(
                    agent_activities.classify_event_importance,
                    ClassifyInput(
                        order_ctx=self._order_ctx,
                        event=event,
                        memory_summary=self._memory_summary,
                    ),
                    start_to_close_timeout=CLASSIFY_ACTIVITY_TIMEOUT,
                    retry_policy=DEFAULT_RETRY_POLICY,
                )
            except ActivityError as exc:
                workflow.logger.exception("classify_event_importance failed after retries")
                classify_result = ClassifyResult(
                    important=True,
                    reasoning=f"Classification failed after retries: {exc}",
                )

            self._append_timeline(
                f"event:{event.type}",
                {
                    "payload": event.payload,
                    "important": classify_result.important,
                    "reasoning": classify_result.reasoning,
                },
            )
            important_event_seen = important_event_seen or classify_result.important

        return important_event_seen

    async def _execute_tool_call(self, tool_call: ToolCall) -> bool:
        assert self._order_ctx is not None

        activity_fn = self._tool_activity_map.get(tool_call.name)
        if activity_fn is None:
            self._append_timeline(
                "tool_failed",
                {
                    "tool": tool_call.name,
                    "args": tool_call.args,
                    "error": f"unknown tool '{tool_call.name}'",
                },
            )
            return False

        # Fix M1: previously built positional args from `dict.values()`,
        # which depends on the LLM emitting JSON keys in exactly the order
        # documented in TOOL_SCHEMAS. That happened to work only because
        # every tool currently has exactly one property. Passing the args
        # dict as a single argument and letting each activity destructure
        # by name removes that ordering dependency entirely.
        call_args = [self._order_ctx.order_id, dict(tool_call.args)]

        try:
            result = await workflow.execute_activity(
                activity_fn,
                args=call_args,
                start_to_close_timeout=TOOL_ACTIVITY_TIMEOUT,
                retry_policy=TOOL_RETRY_POLICY,
            )
        except ActivityError as exc:
            self._append_timeline(
                "tool_failed",
                {
                    "tool": tool_call.name,
                    "args": tool_call.args,
                    "error": str(exc),
                },
            )
            return False

        self._append_timeline(
            f"tool:{tool_call.name}",
            {"args": tool_call.args, "result": result},
        )
        if tool_call.name == "schedule_next_wakeup":
            self._next_wake_at = result
            self._append_timeline(
                "wake_scheduled",
                {"next_wake_at": result.isoformat()},
            )
            return True
        return False

    def _seconds_until_wake(self) -> float | None:
        if self._next_wake_at is None:
            return None
        delta = (self._next_wake_at - workflow.now()).total_seconds()
        return max(delta, 0.0)

    def _append_timeline(self, kind: str, payload: dict[str, Any]) -> None:
        entry = TimelineEntry(ts=workflow.now(), kind=kind, payload=payload)
        self._timeline.append(entry)
        if kind.startswith("event:") or kind in INBOUND_EVENT_KINDS:
            self._pending_event_entries.append(entry)
        else:
            self._pending_action_entries.append(entry)

    async def _persist_snapshot(self) -> bool:
        assert self._order_ctx is not None

        try:
            await workflow.execute_activity(
                persistence_activities.persist_snapshot,
                args=[
                    self._order_ctx.order_id,
                    self._status,
                    self._next_wake_at,
                    list(self._pending_event_entries),
                    list(self._pending_action_entries),
                ],
                start_to_close_timeout=PERSIST_ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
        except ActivityError as exc:
            workflow.logger.exception("persist_snapshot failed after retries")
            self._append_timeline(
                "persistence_failed",
                {"error": str(exc), "pending_entries_retained": True},
            )
            return False
        self._pending_event_entries.clear()
        self._pending_action_entries.clear()
        return True

    def _carryover_input(self) -> SupervisorInput:
        assert self._order_ctx is not None
        return SupervisorInput(
            order_ctx=self._order_ctx,
            initial_memory=self._memory_summary,
            initial_status=self._status,
            initial_timeline=self._timeline[-TIMELINE_TRUNCATION_LENGTH:],
            initial_extra_instructions=list(self._extra_instructions),
            initial_next_wake_at=self._next_wake_at,
        )

    async def _finalize_termination(self) -> None:
        assert self._order_ctx is not None

        if self._pending_events:
            await self._drain_pending_events()
        await self._run_agent(
            "final_summary",
            terminal_status="terminated",
            close_reason="terminated_by_signal",
        )

        if self._status != "terminated":
            self._status = "terminated"
            self._next_wake_at = None
            self._append_timeline("terminated", {"reason": "terminated_by_signal"})
            await self._persist_snapshot()

    # ------------------------------------------------------------------ #
    # Signals
    # ------------------------------------------------------------------ #

    @workflow.signal
    def submit_event(self, event: OrderEvent) -> None:
        if self._status in TERMINAL_STATUSES or self._terminate_requested:
            return
        self._pending_events.append(event)

    @workflow.signal
    def add_instruction(self, instruction: str) -> None:
        if self._status in TERMINAL_STATUSES or self._terminate_requested:
            return
        self._extra_instructions.append(instruction)
        self._append_timeline("instruction_added", {"instruction": instruction})
        self._wake_requested = True
        self._wake_reason = "signal"

    @workflow.signal
    def interrupt(self) -> None:
        if self._status in TERMINAL_STATUSES or self._terminate_requested:
            return
        self._status = "paused"
        self._append_timeline("interrupted", {})

    @workflow.signal
    def resume(self) -> None:
        if self._status != "paused":
            return
        self._status = "active"
        self._append_timeline("resumed", {})
        self._wake_requested = True
        self._wake_reason = "signal"

    @workflow.signal
    def terminate(self) -> None:
        if self._status in TERMINAL_STATUSES or self._terminate_requested:
            return
        self._terminate_requested = True
        self._append_timeline("terminate_requested", {})

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    @workflow.query
    def get_state(self) -> RunState:
        assert self._order_ctx is not None
        return RunState(
            run_id=self._order_ctx.order_id,
            status=self._status,
            next_wake_at=self._next_wake_at,
            memory_summary=self._memory_summary,
        )

    @workflow.query
    def get_timeline(self) -> list[TimelineEntry]:
        return list(self._timeline)

    @workflow.query
    def get_memory(self) -> str:
        return self._memory_summary
