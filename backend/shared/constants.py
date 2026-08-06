"""
shared/constants.py

Centralized constants shared between the workflow, worker, and API layers.
Kept dependency-free (no Temporal / SQLAlchemy imports) so it can be safely
imported from inside `workflow.unsafe.imports_passed_through()` blocks.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Workflow history management
# --------------------------------------------------------------------------
#
# Number of timeline entries accumulated in-memory before the workflow
# calls `continue_as_new` to reset its event history and avoid hitting
# Temporal's history-size limits on long-lived runs.
CONTINUE_AS_NEW_THRESHOLD: int = 200

# Number of most-recent timeline entries passed to the agent as context on
# each step. Keeps the agent prompt bounded even when the full in-memory
# timeline is large.
TIMELINE_TRUNCATION_LENGTH: int = 50

# --------------------------------------------------------------------------
# Run status
# --------------------------------------------------------------------------
#
# Statuses at which the main workflow loop stops processing further
# events/wakeups. Used by both the workflow (loop condition) and the API
# (to decide whether to query live state or fall back to the DB mirror).
TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "terminated"})

# --------------------------------------------------------------------------
# Temporal task queue
# --------------------------------------------------------------------------
#
# Shared by the worker (registration) and the API (`start_workflow` calls),
# so both sides stay in sync without duplicating the literal string.
#
# `TASK_QUEUE` is the single canonical name used across the codebase
# (worker.py, api/routers/runs.py).
TASK_QUEUE: str = "order-supervisor"


def workflow_id_for_order(order_id: str) -> str:
    """Return the canonical Temporal workflow id for an order."""
    return f"order-supervisor-{order_id}"
