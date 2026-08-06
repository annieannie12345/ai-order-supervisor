"""
Seed production-quality demo data for dashboards, screenshots, and E2E tests.

Usage:
    python -m scripts.seed_demo_data
    python -m scripts.seed_demo_data --runs 30
    python -m scripts.seed_demo_data --dry-run

The script creates:
    - 5 supervisors
    - 20-30 runs, default 25
    - chronological event and action timelines for every run

The project currently supports these persisted RunStatus enum values:
`active`, `paused`, `done`, and `terminated`. Demo scenario labels requested
by stakeholders are preserved in payload metadata as:
`ACTIVE`, `WAITING`, `INTERRUPTED`, `COMPLETED`, and `TERMINATED`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from db.models import Action, ActionType, Event, EventType, Run, RunStatus, Supervisor
from db.session import async_session_factory, dispose_engine
from scripts.reset_demo_data import reset_demo_data
from shared.constants import workflow_id_for_order

logger = logging.getLogger("seed_demo_data")

DEFAULT_RUN_COUNT = 25
MIN_RUN_COUNT = 20
MAX_RUN_COUNT = 30
RANDOM_SEED = 20260704


@dataclass(frozen=True)
class SupervisorSeed:
    id: str
    name: str
    base_instruction: str
    tools: list[str]
    wake_policy: dict[str, Any]
    model_config: dict[str, Any]


@dataclass(frozen=True)
class ScenarioTemplate:
    key: str
    title: str
    supervisor_id: str
    demo_status: str
    db_status: RunStatus
    next_wake_minutes: int | None
    customer: dict[str, Any]
    items: list[dict[str, Any]]
    order_total: float
    event_specs: list[dict[str, Any]]
    tool_actions: list[dict[str, Any]]
    summary: str


SUPERVISORS: list[SupervisorSeed] = [
    SupervisorSeed(
        id="demo-supervisor-fulfillment",
        name="Fulfillment Monitor",
        base_instruction=(
            "Monitor fulfillment events, detect shipment risk, leave concise "
            "internal notes, and message customers before delivery expectations slip."
        ),
        tools=[
            "send_customer_message",
            "create_internal_note",
            "mark_for_review",
            "schedule_next_wakeup",
        ],
        wake_policy={
            "routine_events": "log_only",
            "wake_immediately": ["shipment_delayed", "delivery_failed", "customer_message"],
            "default_wake_minutes": 60,
        },
        model_config={"model": "gpt-4.1-mini", "temperature": 0.2},
    ),
    SupervisorSeed(
        id="demo-supervisor-payments",
        name="Payments & Refunds Supervisor",
        base_instruction=(
            "Review payment, refund, and chargeback events. Escalate financial "
            "exceptions and close workflows once payment or refund outcomes are final."
        ),
        tools=[
            "create_internal_note",
            "escalate_issue",
            "mark_for_review",
            "close_workflow",
        ],
        wake_policy={
            "routine_events": "log_only",
            "wake_immediately": ["refund_requested", "payment_failed", "chargeback_opened"],
            "default_wake_minutes": 30,
        },
        model_config={"model": "gpt-4.1-mini", "temperature": 0.1},
    ),
    SupervisorSeed(
        id="demo-supervisor-vip-care",
        name="VIP Customer Care",
        base_instruction=(
            "Prioritize high-value customers, respond quickly to concern signals, "
            "and coordinate proactive updates until the customer confirms resolution."
        ),
        tools=[
            "send_customer_message",
            "create_internal_note",
            "escalate_issue",
            "schedule_next_wakeup",
            "close_workflow",
        ],
        wake_policy={
            "routine_events": "wake_if_vip",
            "wake_immediately": ["customer_message", "shipment_delayed", "delivery_failed"],
            "default_wake_minutes": 15,
        },
        model_config={"model": "gpt-4.1", "temperature": 0.25},
    ),
    SupervisorSeed(
        id="demo-supervisor-risk",
        name="Fraud & Risk Review",
        base_instruction=(
            "Monitor risk flags, address mismatches, and unusual payment patterns. "
            "Escalate high-risk orders and document the reason for every decision."
        ),
        tools=[
            "create_internal_note",
            "mark_for_review",
            "escalate_issue",
            "close_workflow",
        ],
        wake_policy={
            "wake_immediately": ["risk_flag_created", "payment_failed"],
            "risk_score_threshold": 70,
            "default_wake_minutes": 20,
        },
        model_config={"model": "gpt-4.1-mini", "temperature": 0.0},
    ),
    SupervisorSeed(
        id="demo-supervisor-returns",
        name="Returns Resolution",
        base_instruction=(
            "Handle post-delivery return, damaged-item, exchange, and refund workflows. "
            "Keep customers updated and close only when the resolution is confirmed."
        ),
        tools=[
            "send_customer_message",
            "create_internal_note",
            "mark_for_review",
            "escalate_issue",
            "close_workflow",
        ],
        wake_policy={
            "wake_immediately": ["return_requested", "refund_requested", "customer_message"],
            "default_wake_minutes": 30,
        },
        model_config={"model": "gpt-4.1-mini", "temperature": 0.2},
    ),
]


CUSTOMERS = [
    {"id": "cus_10091", "name": "Maya Chen", "email": "maya.chen@example.com", "tier": "standard", "city": "Austin", "region": "TX"},
    {"id": "cus_10144", "name": "Jordan Patel", "email": "jordan.patel@example.com", "tier": "vip", "city": "Seattle", "region": "WA"},
    {"id": "cus_10218", "name": "Elena Garcia", "email": "elena.garcia@example.com", "tier": "standard", "city": "Denver", "region": "CO"},
    {"id": "cus_10302", "name": "Marcus Brooks", "email": "marcus.brooks@example.com", "tier": "vip", "city": "Atlanta", "region": "GA"},
    {"id": "cus_10377", "name": "Priya Shah", "email": "priya.shah@example.com", "tier": "standard", "city": "San Jose", "region": "CA"},
    {"id": "cus_10406", "name": "Noah Williams", "email": "noah.williams@example.com", "tier": "standard", "city": "Boston", "region": "MA"},
]

CATALOG = [
    {"sku": "BAG-TRAVEL-21", "name": "Carry-on travel backpack", "unit_price": 129.95},
    {"sku": "HDPHN-PRO-2", "name": "Wireless noise-cancelling headphones", "unit_price": 249.0},
    {"sku": "KTCN-SET-8", "name": "Ceramic kitchen set", "unit_price": 84.5},
    {"sku": "JKT-RAIN-M", "name": "Waterproof commuter jacket", "unit_price": 159.0},
    {"sku": "CAM-DOOR-4K", "name": "4K smart door camera", "unit_price": 199.99},
    {"sku": "SHOE-RUN-10", "name": "Stability running shoes", "unit_price": 118.0},
    {"sku": "TOY-ROBOT-7", "name": "Programmable robot kit", "unit_price": 74.95},
    {"sku": "LAMP-DESK-LED", "name": "Adjustable LED desk lamp", "unit_price": 46.0},
]


def _event(event_type: str, important: bool, **payload: Any) -> dict[str, Any]:
    return {"event_type": event_type, "important": important, "payload": payload}


SCENARIOS: list[ScenarioTemplate] = [
    ScenarioTemplate(
        key="normal_fulfillment",
        title="Normal fulfillment monitoring",
        supervisor_id="demo-supervisor-fulfillment",
        demo_status="WAITING",
        db_status=RunStatus.ACTIVE,
        next_wake_minutes=45,
        customer=CUSTOMERS[0],
        items=[CATALOG[0]],
        order_total=141.64,
        event_specs=[
            _event("payment_received", False, provider="stripe", payment_method="card", captured=True),
            _event("shipment_created", False, carrier="UPS", service_level="Ground", estimated_delivery_days=4),
        ],
        tool_actions=[
            {"tool": "create_internal_note", "result_status": "created", "note": "Payment and shipment are on track; monitoring until first delivery scan."},
            {"tool": "schedule_next_wakeup", "result_status": "scheduled", "reason": "Check carrier scan before cutoff."},
        ],
        summary="Shipment is in transit and the next carrier scan check is scheduled before cutoff.",
    ),
    ScenarioTemplate(
        key="shipment_delayed_customer_concern",
        title="Delayed shipment with customer concern",
        supervisor_id="demo-supervisor-vip-care",
        demo_status="ACTIVE",
        db_status=RunStatus.ACTIVE,
        next_wake_minutes=15,
        customer=CUSTOMERS[1],
        items=[CATALOG[1]],
        order_total=271.41,
        event_specs=[
            _event("payment_received", False, provider="stripe", payment_method="card", captured=True),
            _event("shipment_created", False, carrier="FedEx", service_level="2Day", estimated_delivery_days=2),
            _event("shipment_delayed", True, carrier="FedEx", delay_reason="weather at Memphis hub", delay_hours=24),
            _event("customer_message", True, channel="email", sentiment="concerned", body="This is a birthday gift. Will it still arrive tomorrow?"),
        ],
        tool_actions=[
            {"tool": "send_customer_message", "result_status": "sent", "message": "We are tracking the delay and will update you as soon as the carrier posts the next scan."},
            {"tool": "create_internal_note", "result_status": "created", "note": "VIP customer notified about carrier delay; monitor next FedEx scan."},
            {"tool": "schedule_next_wakeup", "result_status": "scheduled", "reason": "VIP follow-up after carrier scan refresh."},
        ],
        summary="VIP customer is concerned about a delayed gift shipment; agent responded and scheduled a near-term carrier scan follow-up.",
    ),
    ScenarioTemplate(
        key="refund_requested_late_delivery",
        title="Refund requested after late delivery",
        supervisor_id="demo-supervisor-payments",
        demo_status="ACTIVE",
        db_status=RunStatus.ACTIVE,
        next_wake_minutes=None,
        customer=CUSTOMERS[2],
        items=[CATALOG[2]],
        order_total=92.11,
        event_specs=[
            _event("payment_received", False, provider="paypal", payment_method="paypal", captured=True),
            _event("shipment_delayed", True, carrier="USPS", delay_reason="missed facility departure", delay_hours=48),
            _event("refund_requested", True, reason="arrived too late for event", requested_amount=92.11, customer_tone="frustrated"),
        ],
        tool_actions=[
            {"tool": "escalate_issue", "result_status": "escalated", "reason": "Refund requested after late delivery; policy review required."},
            {"tool": "mark_for_review", "result_status": "flagged_for_review", "reason": "Verify delivery date against refund policy."},
        ],
        summary="Refund request is open after a late delivery; payment supervisor escalated for human policy review.",
    ),
    ScenarioTemplate(
        key="carrier_investigation_paused",
        title="Carrier investigation paused",
        supervisor_id="demo-supervisor-fulfillment",
        demo_status="INTERRUPTED",
        db_status=RunStatus.PAUSED,
        next_wake_minutes=None,
        customer=CUSTOMERS[3],
        items=[CATALOG[3]],
        order_total=173.31,
        event_specs=[
            _event("payment_received", False, provider="stripe", payment_method="card", captured=True),
            _event("shipment_created", False, carrier="UPS", service_level="Ground", estimated_delivery_days=5),
            _event("delivery_failed", True, carrier="UPS", reason="business closed", attempted_at_offset_hours=-4),
        ],
        tool_actions=[
            {"tool": "create_internal_note", "result_status": "created", "note": "Delivery failed; carrier investigation opened."},
            {"tool": "mark_for_review", "result_status": "flagged_for_review", "reason": "Pause while carrier confirms redelivery options."},
        ],
        summary="Delivery failed and the workflow is paused while a carrier investigation is pending.",
    ),
    ScenarioTemplate(
        key="fraud_review_paused",
        title="Fraud review paused",
        supervisor_id="demo-supervisor-risk",
        demo_status="INTERRUPTED",
        db_status=RunStatus.PAUSED,
        next_wake_minutes=None,
        customer=CUSTOMERS[4],
        items=[CATALOG[4]],
        order_total=217.49,
        event_specs=[
            _event("payment_received", True, provider="stripe", payment_method="card", captured=True, risk_score=82),
            _event("risk_flag_created", True, risk_score=82, reason_codes=["address_distance", "velocity"], billing_shipping_distance_miles=1120),
        ],
        tool_actions=[
            {"tool": "mark_for_review", "result_status": "flagged_for_review", "reason": "Risk score exceeds review threshold."},
            {"tool": "escalate_issue", "result_status": "escalated", "reason": "Address mismatch and order velocity require manual fraud review."},
        ],
        summary="High-risk payment and address mismatch are paused for manual fraud review.",
    ),
    ScenarioTemplate(
        key="vip_replacement_resolved",
        title="VIP replacement resolved",
        supervisor_id="demo-supervisor-vip-care",
        demo_status="COMPLETED",
        db_status=RunStatus.DONE,
        next_wake_minutes=None,
        customer=CUSTOMERS[1],
        items=[CATALOG[5]],
        order_total=128.62,
        event_specs=[
            _event("customer_message", True, channel="chat", sentiment="upset", body="The wrong shoe size arrived."),
            _event("shipment_created", False, carrier="UPS", service_level="Next Day Air", estimated_delivery_days=1),
            _event("delivery_confirmed", False, carrier="UPS", signed_by="Jordan Patel"),
        ],
        tool_actions=[
            {"tool": "send_customer_message", "result_status": "sent", "message": "Replacement shipment is on the way with expedited delivery."},
            {"tool": "create_internal_note", "result_status": "created", "note": "VIP replacement shipped and confirmed delivered."},
            {"tool": "close_workflow", "result_status": "closed", "outcome": "replacement_delivered"},
        ],
        summary="VIP replacement order was delivered and the customer confirmed the issue is resolved.",
    ),
    ScenarioTemplate(
        key="payment_completed_cleanly",
        title="Payment completed cleanly",
        supervisor_id="demo-supervisor-payments",
        demo_status="COMPLETED",
        db_status=RunStatus.DONE,
        next_wake_minutes=None,
        customer=CUSTOMERS[5],
        items=[CATALOG[6]],
        order_total=81.70,
        event_specs=[
            _event("payment_received", False, provider="stripe", payment_method="wallet", captured=True),
            _event("shipment_created", False, carrier="USPS", service_level="Priority", estimated_delivery_days=3),
            _event("delivery_confirmed", False, carrier="USPS", signed_by="N. Williams"),
        ],
        tool_actions=[
            {"tool": "create_internal_note", "result_status": "created", "note": "Payment captured and delivery completed without exceptions."},
            {"tool": "close_workflow", "result_status": "closed", "outcome": "completed_no_exceptions"},
        ],
        summary="Payment, shipment, and delivery completed cleanly with no further action needed.",
    ),
    ScenarioTemplate(
        key="cancelled_upstream",
        title="Cancelled upstream",
        supervisor_id="demo-supervisor-fulfillment",
        demo_status="TERMINATED",
        db_status=RunStatus.TERMINATED,
        next_wake_minutes=None,
        customer=CUSTOMERS[0],
        items=[CATALOG[7]],
        order_total=50.14,
        event_specs=[
            _event("payment_received", False, provider="stripe", payment_method="card", captured=True),
            _event("order_cancelled", True, reason="customer cancelled before fulfillment", cancellation_source="commerce_admin"),
        ],
        tool_actions=[
            {"tool": "create_internal_note", "result_status": "created", "note": "Order cancelled upstream before fulfillment handoff."},
        ],
        summary="Run was terminated because the order was cancelled upstream before fulfillment.",
    ),
    ScenarioTemplate(
        key="duplicate_workflow_terminated",
        title="Duplicate workflow consolidated",
        supervisor_id="demo-supervisor-risk",
        demo_status="TERMINATED",
        db_status=RunStatus.TERMINATED,
        next_wake_minutes=None,
        customer=CUSTOMERS[3],
        items=[CATALOG[4]],
        order_total=217.49,
        event_specs=[
            _event("risk_flag_created", True, risk_score=74, reason_codes=["duplicate_order"], duplicate_order_id="ORD-921884"),
        ],
        tool_actions=[
            {"tool": "create_internal_note", "result_status": "created", "note": "Duplicate workflow consolidated into primary risk review run."},
        ],
        summary="Duplicate workflow was terminated after consolidation into the primary risk review.",
    ),
    ScenarioTemplate(
        key="damaged_item_return",
        title="Damaged item return",
        supervisor_id="demo-supervisor-returns",
        demo_status="WAITING",
        db_status=RunStatus.ACTIVE,
        next_wake_minutes=30,
        customer=CUSTOMERS[2],
        items=[CATALOG[2]],
        order_total=92.11,
        event_specs=[
            _event("delivery_confirmed", False, carrier="FedEx", signed_by="E. Garcia"),
            _event("return_requested", True, reason="item arrived chipped", item_condition="damaged", preferred_resolution="replacement"),
            _event("customer_message", True, channel="email", sentiment="disappointed", body="The bowl set arrived chipped. Can you replace it?"),
        ],
        tool_actions=[
            {"tool": "send_customer_message", "result_status": "sent", "message": "We are sorry the item arrived damaged. We are reviewing replacement options now."},
            {"tool": "mark_for_review", "result_status": "flagged_for_review", "reason": "Damaged item replacement request requires inventory confirmation."},
            {"tool": "schedule_next_wakeup", "result_status": "scheduled", "reason": "Check replacement inventory and follow up."},
        ],
        summary="Damaged item return is active; customer was acknowledged and replacement inventory needs follow-up.",
    ),
]


def _money(value: float) -> float:
    return round(value, 2)


def _order_payload(order_id: str, scenario: ScenarioTemplate, created_at: datetime) -> dict[str, Any]:
    subtotal = sum(item["unit_price"] for item in scenario.items)
    tax = _money(subtotal * 0.0825)
    shipping = 0.0 if subtotal >= 100 else 6.95
    return {
        "order_number": order_id,
        "customer": scenario.customer,
        "items": [
            {
                "sku": item["sku"],
                "name": item["name"],
                "quantity": 1,
                "unit_price": item["unit_price"],
            }
            for item in scenario.items
        ],
        "subtotal": _money(subtotal),
        "tax": tax,
        "shipping": shipping,
        "total": _money(subtotal + tax + shipping),
        "currency": "USD",
        "channel": random.choice(["web", "mobile_app", "marketplace"]),
        "placed_at": created_at.isoformat(),
        "shipping_address": {
            "city": scenario.customer["city"],
            "region": scenario.customer["region"],
            "country": "US",
        },
        "demo_scenario": scenario.key,
        "demo_status": scenario.demo_status,
    }


def _event_payload(
    order_id: str,
    event_type: str,
    base_payload: dict[str, Any],
    ts: datetime,
    index: int,
) -> dict[str, Any]:
    payload = {
        "event_type": event_type,
        "order_id": order_id,
        "source": "demo_seed",
        "external_event_id": f"evt_demo_{order_id.lower().replace('-', '_')}_{index:02d}",
        "observed_at": ts.isoformat(),
        **base_payload,
    }
    if event_type == "payment_received":
        payload.setdefault("payment_id", f"pay_{order_id[-6:].lower()}_{index:02d}")
    if event_type in {"shipment_created", "shipment_delayed", "delivery_failed", "delivery_confirmed"}:
        payload.setdefault("shipment_id", f"shp_{order_id[-6:].lower()}")
        payload.setdefault("tracking_number", f"1Z{order_id[-6:]}{index:02d}DEMO")
    if event_type in {"customer_message", "refund_requested", "return_requested"}:
        payload.setdefault("case_id", f"case_{order_id[-6:].lower()}")
    return payload


def _tool_result(order_id: str, action: dict[str, Any], ts: datetime, ordinal: int) -> dict[str, Any]:
    tool = action["tool"]
    result_status = action["result_status"]
    common = {
        "status": result_status,
        "order_id": order_id,
        "provider": "demo",
        "completed_at": ts.isoformat(),
    }
    if tool == "send_customer_message":
        return {
            **common,
            "message_id": f"msg_{order_id[-6:].lower()}_{ordinal:02d}",
            "channel": "email",
            "message": action["message"],
        }
    if tool == "create_internal_note":
        return {
            **common,
            "note_id": f"note_{order_id[-6:].lower()}_{ordinal:02d}",
            "visibility": "internal",
            "note": action["note"],
        }
    if tool == "mark_for_review":
        return {
            **common,
            "review_id": f"rev_{order_id[-6:].lower()}_{ordinal:02d}",
            "priority": "normal",
            "reason": action["reason"],
        }
    if tool == "escalate_issue":
        return {
            **common,
            "ticket_id": f"esc_{order_id[-6:].lower()}_{ordinal:02d}",
            "priority": "high",
            "assigned_queue": "order-specialists",
            "reason": action["reason"],
        }
    if tool == "schedule_next_wakeup":
        return {
            **common,
            "wake_id": f"wake_{order_id[-6:].lower()}_{ordinal:02d}",
            "reason": action["reason"],
        }
    if tool == "close_workflow":
        return {
            **common,
            "closure_id": f"close_{order_id[-6:].lower()}_{ordinal:02d}",
            "outcome": action["outcome"],
        }
    return common


def _build_events(
    run_id: str,
    order_id: str,
    scenario: ScenarioTemplate,
    start_at: datetime,
) -> list[Event]:
    events: list[Event] = []
    for index, spec in enumerate(scenario.event_specs, start=1):
        ts = start_at + timedelta(minutes=5 + index * random.randint(7, 16))
        events.append(
            Event(
                run_id=run_id,
                ts=ts,
                type=EventType.ORDER_EVENT,
                payload=_event_payload(
                    order_id,
                    spec["event_type"],
                    spec["payload"],
                    ts,
                    index,
                ),
                important=spec["important"],
            )
        )

    if scenario.demo_status == "INTERRUPTED":
        events.append(
            Event(
                run_id=run_id,
                ts=start_at + timedelta(minutes=52),
                type=EventType.INTERRUPT,
                payload={
                    "reason": "Human review requested from demo workflow control.",
                    "source": "demo_seed",
                    "demo_status": scenario.demo_status,
                },
                important=True,
            )
        )
    elif scenario.demo_status == "TERMINATED":
        events.append(
            Event(
                run_id=run_id,
                ts=start_at + timedelta(minutes=58),
                type=EventType.TERMINATE,
                payload={
                    "reason": "Demo terminal scenario reached.",
                    "source": "demo_seed",
                    "demo_status": scenario.demo_status,
                },
                important=True,
            )
        )

    return sorted(events, key=lambda event: event.ts)


def _build_actions(
    run_id: str,
    order_id: str,
    scenario: ScenarioTemplate,
    start_at: datetime,
    next_wake_at: datetime | None,
) -> list[Action]:
    actions: list[Action] = [
        Action(
            run_id=run_id,
            ts=start_at + timedelta(minutes=2),
            type=ActionType.AGENT_ACTION,
            payload={
                "reason": "workflow_start",
                "forced": False,
                "actions_taken": {
                    "mode": "demo_seed",
                    "scenario": scenario.key,
                    "demo_status": scenario.demo_status,
                    "decision": "Opened supervision and inspected initial order context.",
                },
            },
        )
    ]

    for ordinal, tool_action in enumerate(scenario.tool_actions, start=1):
        ts = start_at + timedelta(minutes=28 + ordinal * 6)
        tool = tool_action["tool"]
        args = {
            key: value
            for key, value in tool_action.items()
            if key not in {"tool", "result_status"}
        }
        actions.append(
            Action(
                run_id=run_id,
                ts=ts,
                type=ActionType.TOOL_CALL,
                payload={
                    "tool": tool,
                    "args": args,
                    "result": _tool_result(order_id, tool_action, ts, ordinal),
                },
            )
        )

    if next_wake_at is not None:
        actions.append(
            Action(
                run_id=run_id,
                ts=start_at + timedelta(minutes=47),
                type=ActionType.WAKE_SCHEDULED,
                payload={
                    "next_wake_at": next_wake_at.isoformat(),
                    "reason": "Demo scenario follow-up.",
                },
            )
        )

    actions.append(
        Action(
            run_id=run_id,
            ts=start_at + timedelta(minutes=50),
            type=ActionType.MEMORY_UPDATED,
            payload={
                "summary": scenario.summary,
                "demo_status": scenario.demo_status,
                "scenario": scenario.key,
            },
        )
    )

    if scenario.db_status == RunStatus.DONE:
        actions.append(
            Action(
                run_id=run_id,
                ts=start_at + timedelta(minutes=68),
                type=ActionType.FINAL_SUMMARY,
                payload={
                    "summary": scenario.summary,
                    "forced": False,
                    "actions_taken": {
                        "type": "final_summary",
                        "scenario": scenario.key,
                        "outcome": "completed",
                    },
                },
            )
        )
        actions.append(
            Action(
                run_id=run_id,
                ts=start_at + timedelta(minutes=70),
                type=ActionType.LIFECYCLE,
                payload={"reason": "agent_requested", "demo_status": scenario.demo_status},
            )
        )
    elif scenario.db_status == RunStatus.TERMINATED:
        actions.append(
            Action(
                run_id=run_id,
                ts=start_at + timedelta(minutes=66),
                type=ActionType.FINAL_SUMMARY,
                payload={
                    "summary": scenario.summary,
                    "forced": False,
                    "actions_taken": {
                        "type": "final_summary",
                        "scenario": scenario.key,
                        "outcome": "terminated",
                    },
                },
            )
        )
        actions.append(
            Action(
                run_id=run_id,
                ts=start_at + timedelta(minutes=69),
                type=ActionType.LIFECYCLE,
                payload={
                    "reason": "terminated_by_signal",
                    "demo_status": scenario.demo_status,
                },
            )
        )
    elif scenario.db_status == RunStatus.PAUSED:
        actions.append(
            Action(
                run_id=run_id,
                ts=start_at + timedelta(minutes=60),
                type=ActionType.LIFECYCLE,
                payload={
                    "reason": "interrupted_for_human_review",
                    "demo_status": scenario.demo_status,
                },
            )
        )

    return sorted(actions, key=lambda action: action.ts)


def _scenario_for_index(index: int) -> ScenarioTemplate:
    return SCENARIOS[(index - 1) % len(SCENARIOS)]


def _order_id_for_index(index: int, now: datetime) -> str:
    return f"ORD-DEMO-{now:%y%m}-{1000 + index:04d}"


def _run_id_for_index(index: int) -> str:
    return f"demo-run-{index:04d}"


async def seed_demo_data(run_count: int = DEFAULT_RUN_COUNT, *, dry_run: bool = False) -> None:
    if run_count < MIN_RUN_COUNT or run_count > MAX_RUN_COUNT:
        raise ValueError(f"--runs must be between {MIN_RUN_COUNT} and {MAX_RUN_COUNT}")

    random.seed(RANDOM_SEED)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    if dry_run:
        print(
            f"Dry run: would reset demo data and seed {len(SUPERVISORS)} supervisors, "
            f"{run_count} runs, timelines, events, and actions."
        )
        return

    reset_result = await reset_demo_data()
    logger.info("Reset existing demo data before seeding: %s", reset_result)

    async with async_session_factory() as session:
        supervisors = [
            Supervisor(
                id=supervisor.id,
                name=supervisor.name,
                base_instruction=supervisor.base_instruction,
                tools=supervisor.tools,
                wake_policy=supervisor.wake_policy,
                model_config_=supervisor.model_config,
                created_at=now - timedelta(days=7),
                updated_at=now - timedelta(days=1),
            )
            for supervisor in SUPERVISORS
        ]
        session.add_all(supervisors)

        total_events = 0
        total_actions = 0
        status_counts: dict[str, int] = {}

        for index in range(1, run_count + 1):
            scenario = _scenario_for_index(index)
            run_id = _run_id_for_index(index)
            order_id = _order_id_for_index(index, now)
            start_at = now - timedelta(hours=run_count - index + 3, minutes=random.randint(0, 45))
            next_wake_at = (
                now + timedelta(minutes=scenario.next_wake_minutes + random.randint(0, 12))
                if scenario.next_wake_minutes is not None
                else None
            )
            last_activity_at = start_at + timedelta(minutes=75)

            run = Run(
                id=run_id,
                order_id=order_id,
                supervisor_id=scenario.supervisor_id,
                workflow_id=workflow_id_for_order(order_id),
                status=scenario.db_status,
                next_wake_at=next_wake_at,
                created_at=start_at,
                updated_at=last_activity_at,
            )
            session.add(run)

            events = _build_events(run_id, order_id, scenario, start_at)
            actions = _build_actions(run_id, order_id, scenario, start_at, next_wake_at)

            # Store order context on the first agent action so demos can inspect
            # realistic payloads without adding a new table or changing schemas.
            order_payload = _order_payload(order_id, scenario, start_at)
            actions[0].payload = {
                **actions[0].payload,
                "order_payload": order_payload,
                "title": scenario.title,
            }

            session.add_all(events)
            session.add_all(actions)

            total_events += len(events)
            total_actions += len(actions)
            status_counts[scenario.demo_status] = status_counts.get(scenario.demo_status, 0) + 1

        await session.commit()

    async with async_session_factory() as session:
        run_total = (
            await session.execute(select(Run).where(Run.id.like("demo-run-%")))
        ).scalars().all()

    print(
        "Seeded demo data: "
        f"supervisors={len(SUPERVISORS)}, "
        f"runs={len(run_total)}, "
        f"events={total_events}, "
        f"actions={total_actions}, "
        f"demo_status_counts={status_counts}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed realistic AI Order Supervisor demo data."
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUN_COUNT,
        help=f"Number of demo runs to create ({MIN_RUN_COUNT}-{MAX_RUN_COUNT}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be seeded without writing to the database.",
    )
    return parser


async def _amain() -> None:
    args = _build_parser().parse_args()
    await seed_demo_data(args.runs, dry_run=args.dry_run)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(_amain())
    finally:
        asyncio.run(dispose_engine())


if __name__ == "__main__":
    main()
