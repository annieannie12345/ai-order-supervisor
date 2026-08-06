"""
shared/retry_policies.py

Shared Temporal `RetryPolicy` definitions used across activity calls in
`workflows/order_supervisor.py`. Centralized here so retry behavior stays
consistent and can be tuned in one place.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio.common import RetryPolicy

# --------------------------------------------------------------------------
# DEFAULT_RETRY_POLICY
# --------------------------------------------------------------------------
#
# Used for the "core" activities that drive workflow state and must not be
# silently skipped: agent steps, event classification, and snapshot
# persistence. Backs off exponentially with a moderate cap and a generous
# (but not unlimited) attempt budget, since these activities are what keep
# the run moving forward — we'd rather keep retrying transient failures
# (LLM provider hiccups, DB connection blips) than give up early and leave
# the workflow stuck.
DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=5,
    non_retryable_error_types=[],
)

# --------------------------------------------------------------------------
# TOOL_RETRY_POLICY
# --------------------------------------------------------------------------
#
# Used for individual tool-call activities (send_customer_message,
# escalate_issue, close_workflow, etc.). These are mocked/idempotent-ish
# side-effecting calls to (eventually) external systems, so retries are
# shorter and more bounded than the core policy: we don't want a single
# flaky tool call (e.g. a downstream notification provider outage) to
# retry for minutes and stall the workflow loop or risk duplicate
# side effects. Failures here are caught by the workflow and recorded as
# `tool_failed` timeline entries rather than being retried indefinitely.
TOOL_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=20),
    maximum_attempts=3,
    non_retryable_error_types=[],
)
