"""
Reset seeded demo data without touching schema or migrations.

Usage:
    python -m scripts.reset_demo_data

Only rows created by scripts.seed_demo_data are removed. The script uses stable
demo id/order/workflow prefixes so it is safe to run in a shared local database
that also contains manually-created test data.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import delete, or_, select

from db.models import Action, Event, Run, Supervisor
from db.session import async_session_factory, dispose_engine

DEMO_RUN_ID_PREFIX = "demo-run-"
DEMO_ORDER_ID_PREFIX = "ORD-DEMO-"
DEMO_WORKFLOW_ID_PREFIX = "order-supervisor-ORD-DEMO-"
DEMO_SUPERVISOR_ID_PREFIX = "demo-supervisor-"

logger = logging.getLogger("reset_demo_data")


@dataclass(frozen=True)
class ResetResult:
    actions_deleted: int
    events_deleted: int
    runs_deleted: int
    supervisors_deleted: int


async def reset_demo_data(*, keep_supervisors: bool = False) -> ResetResult:
    """
    Remove seeded demo rows.

    Deletion order is explicit even though the FK uses cascade delete, because
    returning exact counts is useful for CI logs and demo setup diagnostics.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(Run.id).where(
                or_(
                    Run.id.like(f"{DEMO_RUN_ID_PREFIX}%"),
                    Run.order_id.like(f"{DEMO_ORDER_ID_PREFIX}%"),
                    Run.workflow_id.like(f"{DEMO_WORKFLOW_ID_PREFIX}%"),
                )
            )
        )
        run_ids = list(result.scalars().all())

        actions_deleted = 0
        events_deleted = 0
        runs_deleted = 0
        supervisors_deleted = 0

        if run_ids:
            action_result = await session.execute(
                delete(Action).where(Action.run_id.in_(run_ids))
            )
            event_result = await session.execute(
                delete(Event).where(Event.run_id.in_(run_ids))
            )
            run_result = await session.execute(
                delete(Run).where(Run.id.in_(run_ids))
            )
            actions_deleted = action_result.rowcount or 0
            events_deleted = event_result.rowcount or 0
            runs_deleted = run_result.rowcount or 0

        if not keep_supervisors:
            supervisor_result = await session.execute(
                delete(Supervisor).where(
                    Supervisor.id.like(f"{DEMO_SUPERVISOR_ID_PREFIX}%")
                )
            )
            supervisors_deleted = supervisor_result.rowcount or 0

        await session.commit()

    return ResetResult(
        actions_deleted=actions_deleted,
        events_deleted=events_deleted,
        runs_deleted=runs_deleted,
        supervisors_deleted=supervisors_deleted,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove AI Order Supervisor demo seed data."
    )
    parser.add_argument(
        "--keep-supervisors",
        action="store_true",
        help="Delete demo runs/events/actions but leave demo supervisors in place.",
    )
    return parser


async def _amain() -> None:
    args = _build_parser().parse_args()
    result = await reset_demo_data(keep_supervisors=args.keep_supervisors)
    logger.info(
        "Deleted demo data: actions=%s events=%s runs=%s supervisors=%s",
        result.actions_deleted,
        result.events_deleted,
        result.runs_deleted,
        result.supervisors_deleted,
    )
    print(
        "Deleted demo data: "
        f"actions={result.actions_deleted}, "
        f"events={result.events_deleted}, "
        f"runs={result.runs_deleted}, "
        f"supervisors={result.supervisors_deleted}"
    )


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
