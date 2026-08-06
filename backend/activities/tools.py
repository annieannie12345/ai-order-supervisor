"""
activities/tools.py

Mocked tool activities for the OrderSupervisorWorkflow. Each function here
is one Temporal activity, dispatched from
OrderSupervisorWorkflow._tool_activity_map with the ToolCall's `args` dict
passed through as a single argument (see
order_supervisor.py::_execute_tool_call):

    call_args = [order_id, dict(tool_call.args)]

So each signature below is `(order_id, args: dict[str, Any])`, and each
activity pulls its named field(s) out of `args` itself. (Previously this
built positional args from `dict.values()`, which depended on the LLM
emitting JSON keys in exactly the order documented in TOOL_SCHEMAS — a
landmine the moment any tool gained a second parameter. Fixed per audit M1.)

These are POC mocks: no real side effects (no email/SMS provider, no ticketing
system, no scheduler). Each returns a realistic, structured, JSON-serializable
response as a real integration would, including a fabricated external id and
a UTC timestamp, so downstream timeline/persistence code has something
representative to store and the UI has something to render.

All activities are deliberately simple, fast, and idempotent-ish (repeated
calls with the same args just produce a new mock record — fine for a POC;
a real implementation would take an idempotency key).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from temporalio import activity


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mock_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------- #
# Customer-facing
# --------------------------------------------------------------------- #

@activity.defn
async def send_customer_message(order_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    Mock: send a message to the customer via whatever channel is on file
    (email/SMS/chat). Real implementation would call a notifications
    provider (e.g. SendGrid, Twilio, Intercom) and return their message id.
    """
    activity.logger.info("Mock sending customer message for order %s", order_id)
    message = args["message"]

    message_id = _mock_id("msg")
    return {
        "status": "sent",
        "message_id": message_id,
        "order_id": order_id,
        "channel": "email",
        "message": message,
        "sent_at": _now(),
        "provider": "mock-notifications",
    }


# --------------------------------------------------------------------- #
# Internal-facing
# --------------------------------------------------------------------- #

@activity.defn
async def create_internal_note(order_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    Mock: attach an internal-only note to the order record. Real
    implementation would insert a row into an internal notes/CRM table.
    """
    activity.logger.info("Mock creating internal note for order %s", order_id)
    note = args["note"]

    note_id = _mock_id("note")
    return {
        "status": "created",
        "note_id": note_id,
        "order_id": order_id,
        "note": note,
        "visibility": "internal",
        "created_at": _now(),
    }


@activity.defn
async def escalate_issue(order_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    Mock: escalate to a human specialist/team queue. Real implementation
    would open a ticket (e.g. Zendesk/Jira) and page/route to an on-call
    queue.
    """
    reason = args["reason"]
    activity.logger.info("Mock escalating order %s: %s", order_id, reason)

    ticket_id = _mock_id("esc")
    return {
        "status": "escalated",
        "ticket_id": ticket_id,
        "order_id": order_id,
        "reason": reason,
        "priority": "high",
        "assigned_queue": "order-specialists",
        "escalated_at": _now(),
    }


@activity.defn
async def mark_for_review(order_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    Mock: flag the order for asynchronous human review (lower urgency than
    escalate_issue — no paging, just a queue entry). Real implementation
    would insert a row into a review queue table/dashboard.
    """
    reason = args["reason"]
    activity.logger.info("Mock marking order %s for review: %s", order_id, reason)

    review_id = _mock_id("rev")
    return {
        "status": "flagged_for_review",
        "review_id": review_id,
        "order_id": order_id,
        "reason": reason,
        "priority": "normal",
        "flagged_at": _now(),
    }


# --------------------------------------------------------------------- #
# Workflow control
# --------------------------------------------------------------------- #

@activity.defn
async def schedule_next_wakeup(order_id: str, args: dict[str, Any]) -> datetime:
    """
    Mock: validate/normalize the agent's requested wake time and hand back
    a real datetime the workflow will store as `next_wake_at`. A real
    implementation might clamp this against a min/max policy or snap to a
    business-hours window; here we just parse and pass through.
    """
    when = args["when"]
    activity.logger.info("Mock scheduling next wakeup for order %s at %s", order_id, when)

    try:
        wake_at = datetime.fromisoformat(when)
    except ValueError:
        # Fall back to "1 hour from now" if the model gave a malformed
        # timestamp, rather than failing the whole agent step.
        from datetime import timedelta

        wake_at = datetime.now(timezone.utc) + timedelta(hours=1)

    if wake_at.tzinfo is None:
        wake_at = wake_at.replace(tzinfo=timezone.utc)

    return wake_at


@activity.defn
async def close_workflow(order_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    Mock: perform any final external side effects tied to closing out the
    order-supervision run (e.g. notify downstream systems, close related
    tickets). Real implementation would fan out to whatever systems care
    that supervision has ended.
    """
    outcome = args["outcome"]
    activity.logger.info("Mock closing workflow for order %s: %s", order_id, outcome)

    closure_id = _mock_id("close")
    return {
        "status": "closed",
        "closure_id": closure_id,
        "order_id": order_id,
        "outcome": outcome,
        "closed_at": _now(),
    }
