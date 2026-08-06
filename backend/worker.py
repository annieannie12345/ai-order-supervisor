"""
worker.py

Temporal Worker entrypoint. Registers `OrderSupervisorWorkflow` and every
activity from `activities/agent.py`, `activities/tools.py`, and
`activities/persistence.py` on the configured task queue, then polls until
cancelled (SIGINT/SIGTERM).

Run with:
    python worker.py
"""

from __future__ import annotations

import asyncio
import logging
import signal

from temporalio.worker import Worker

from activities import agent as agent_activities
from activities import persistence as persistence_activities
from activities import tools as tool_activities
from client import get_temporal_client
from config import settings
from shared.constants import TASK_QUEUE
from workflows.order_supervisor import OrderSupervisorWorkflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("worker")


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

WORKFLOWS = [
    OrderSupervisorWorkflow,
]

ACTIVITIES = [
    # activities/agent.py
    agent_activities.classify_event_importance,
    agent_activities.run_agent_step,
    agent_activities.generate_final_summary,
    # activities/tools.py
    tool_activities.send_customer_message,
    tool_activities.create_internal_note,
    tool_activities.escalate_issue,
    tool_activities.mark_for_review,
    tool_activities.schedule_next_wakeup,
    tool_activities.close_workflow,
    # activities/persistence.py
    persistence_activities.persist_snapshot,
]


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------


async def main() -> None:
    client = await get_temporal_client()

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
        # Activities here do async I/O (DB, LLM calls, mocked HTTP) rather
        # than CPU-bound work, so the default asyncio activity executor is
        # sufficient — no activity_executor override needed for this POC.
        max_concurrent_activities=settings.worker_max_concurrent_activities,
        max_concurrent_workflow_tasks=settings.worker_max_concurrent_workflow_tasks,
    )

    logger.info(
        "Starting worker on task_queue=%r namespace=%r target=%r "
        "(workflows=%d, activities=%d)",
        TASK_QUEUE,
        settings.temporal_namespace,
        settings.temporal_target_host,
        len(WORKFLOWS),
        len(ACTIVITIES),
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_stop_signal(sig_name: str) -> None:
        logger.info("Received %s, shutting down worker...", sig_name)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_stop_signal, sig.name)
        except NotImplementedError:
            # add_signal_handler isn't available on some platforms
            # (e.g. Windows); fall back to default KeyboardInterrupt
            # handling for SIGINT in that case.
            pass

    async with worker:
        logger.info("Worker started, polling task queue %r...", TASK_QUEUE)
        await stop_event.wait()

    logger.info("Worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())
