"""
scripts/demo_data.py

Seed a small demo dataset for local dashboards:
    - 3 supervisors
    - 10 sample runs
    - mixed statuses: active, paused, done, terminated

Usage:
    python -m scripts.demo_data

The script replaces only rows with the `demo-` id/order/workflow prefixes, so it
is safe to rerun while preserving non-demo data.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select

from db.models import Action, ActionType, Event, EventType, Run, RunStatus, Supervisor
from db.session import async_session_factory, dispose_engine
from shared.constants import workflow_id_for_order


DEMO_SUPERVISORS: list[dict[str, Any]] = [
    {
        "id": "demo-supervisor-fulfillment",
        "name": "Fulfillment Supervisor",
        "base_instruction": (
            "Monitor fulfillment events, resolve shipping delays, and keep "
            "customers informed with concise status updates."
        ),
        "tools": ["lookup_order", "track_shipment", "send_customer_message"],
        "wake_policy": {"default_minutes": 60, "max_pending_wakes": 2},
        "model_config_": {"model": "gpt-4.1-mini", "temperature": 0.2},
    },
    {
        "id": "demo-supervisor-payments",
        "name": "Payments Supervisor",
        "base_instruction": (
            "Review payment, refund, and chargeback signals while escalating "
            "high-risk financial exceptions."
        ),
        "tools": ["lookup_payment", "issue_refund", "flag_for_review"],
        "wake_policy": {"default_minutes": 30, "max_pending_wakes": 3},
        "model_config_": {"model": "gpt-4.1-mini", "temperature": 0.1},
    },
    {
        "id": "demo-supervisor-vip",
        "name": "VIP Care Supervisor",
        "base_instruction": (
            "Prioritize high-value orders, detect customer frustration early, "
            "and coordinate proactive follow-up."
        ),
        "tools": ["lookup_customer", "apply_credit", "send_customer_message"],
        "wake_policy": {"default_minutes": 15, "max_pending_wakes": 4},
        "model_config_": {"model": "gpt-4.1", "temperature": 0.3},
    },
]


DEMO_RUNS: list[dict[str, Any]] = [
    {
        "id": "demo-run-001",
        "order_id": "demo-order-1001",
        "supervisor_id": "demo-supervisor-fulfillment",
        "status": RunStatus.ACTIVE,
        "next_wake_minutes": 20,
        "summary": "Shipment is in transit; next check is scheduled before carrier cutoff.",
    },
    {
        "id": "demo-run-002",
        "order_id": "demo-order-1002",
        "supervisor_id": "demo-supervisor-payments",
        "status": RunStatus.PAUSED,
        "next_wake_minutes": None,
        "summary": "Payment review is paused while support waits for customer documents.",
    },
    {
        "id": "demo-run-003",
        "order_id": "demo-order-1003",
        "supervisor_id": "demo-supervisor-vip",
        "status": RunStatus.DONE,
        "next_wake_minutes": None,
        "summary": "VIP replacement order was delivered and customer confirmed resolution.",
    },
    {
        "id": "demo-run-004",
        "order_id": "demo-order-1004",
        "supervisor_id": "demo-supervisor-fulfillment",
        "status": RunStatus.TERMINATED,
        "next_wake_minutes": None,
        "summary": "Run was terminated after the order was cancelled upstream.",
    },
    {
        "id": "demo-run-005",
        "order_id": "demo-order-1005",
        "supervisor_id": "demo-supervisor-payments",
        "status": RunStatus.ACTIVE,
        "next_wake_minutes": 45,
        "summary": "Refund request is awaiting processor confirmation.",
    },
    {
        "id": "demo-run-006",
        "order_id": "demo-order-1006",
        "supervisor_id": "demo-supervisor-vip",
        "status": RunStatus.ACTIVE,
        "next_wake_minutes": 10,
        "summary": "Customer asked for an ETA; agent is monitoring shipment scan updates.",
    },
    {
        "id": "demo-run-007",
        "order_id": "demo-order-1007",
        "supervisor_id": "demo-supervisor-fulfillment",
        "status": RunStatus.PAUSED,
        "next_wake_minutes": None,
        "summary": "Carrier investigation is open and the run is paused until a response arrives.",
    },
    {
        "id": "demo-run-008",
        "order_id": "demo-order-1008",
        "supervisor_id": "demo-supervisor-payments",
        "status": RunStatus.DONE,
        "next_wake_minutes": None,
        "summary": "Payment captured successfully and no further action is needed.",
    },
    {
        "id": "demo-run-009",
        "order_id": "demo-order-1009",
        "supervisor_id": "demo-supervisor-vip",
        "status": RunStatus.TERMINATED,
        "next_wake_minutes": None,
        "summary": "Duplicate workflow was terminated after consolidation into another run.",
    },
    {
        "id": "demo-run-010",
        "order_id": "demo-order-1010",
        "supervisor_id": "demo-supervisor-fulfillment",
        "status": RunStatus.ACTIVE,
        "next_wake_minutes": 90,
        "summary": "Delayed shipment has a new ETA and needs a follow-up check.",
    },
]


async def _delete_existing_demo_rows() -> None:
    async with async_session_factory() as session:
        demo_run_ids = (
            await session.execute(select(Run.id).where(Run.id.like("demo-run-%")))
        ).scalars()
        run_ids = list(demo_run_ids)

        if run_ids:
            await session.execute(delete(Action).where(Action.run_id.in_(run_ids)))
            await session.execute(delete(Event).where(Event.run_id.in_(run_ids)))
            await session.execute(delete(Run).where(Run.id.in_(run_ids)))

        await session.execute(
            delete(Supervisor).where(Supervisor.id.like("demo-supervisor-%"))
        )
        await session.commit()


async def seed_demo_data() -> None:
    now = datetime.now(timezone.utc)

    await _delete_existing_demo_rows()

    async with async_session_factory() as session:
        supervisors = [Supervisor(**payload) for payload in DEMO_SUPERVISORS]
        session.add_all(supervisors)

        for index, payload in enumerate(DEMO_RUNS, start=1):
            created_at = now - timedelta(hours=12 - index)
            next_wake_minutes = payload["next_wake_minutes"]
            next_wake_at = (
                now + timedelta(minutes=next_wake_minutes)
                if next_wake_minutes is not None
                else None
            )

            run = Run(
                id=payload["id"],
                order_id=payload["order_id"],
                supervisor_id=payload["supervisor_id"],
                workflow_id=workflow_id_for_order(payload["order_id"]),
                status=payload["status"],
                next_wake_at=next_wake_at,
                created_at=created_at,
                updated_at=created_at + timedelta(minutes=18),
            )
            session.add(run)
            session.add(
                Event(
                    run_id=run.id,
                    ts=created_at + timedelta(minutes=2),
                    type=EventType.ORDER_EVENT,
                    payload={
                        "event_type": "demo_order_update",
                        "order_id": payload["order_id"],
                        "source": "demo_data",
                    },
                    important=payload["status"] in {RunStatus.PAUSED, RunStatus.TERMINATED},
                )
            )
            session.add(
                Action(
                    run_id=run.id,
                    ts=created_at + timedelta(minutes=10),
                    type=ActionType.MEMORY_UPDATED,
                    payload={"memory_summary": payload["summary"]},
                )
            )

            if payload["status"] in {RunStatus.DONE, RunStatus.TERMINATED}:
                action_type = (
                    ActionType.FINAL_SUMMARY
                    if payload["status"] == RunStatus.DONE
                    else ActionType.LIFECYCLE
                )
                session.add(
                    Action(
                        run_id=run.id,
                        ts=created_at + timedelta(minutes=18),
                        type=action_type,
                        payload={"summary": payload["summary"], "status": payload["status"].value},
                    )
                )

        await session.commit()

    print("Seeded demo data: 3 supervisors, 10 runs.")


async def main() -> None:
    try:
        await seed_demo_data()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
