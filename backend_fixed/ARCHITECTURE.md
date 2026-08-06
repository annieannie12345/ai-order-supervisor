# Architecture

## 1. Workflow Ownership

Each order is supervised by one Temporal workflow whose ID is derived from the order ID. The API commits the read-model `runs` row before starting the workflow, so persistence activities can safely attach events and actions to an existing run.

## 3. Run Lifecycle

The workflow status values are `active`, `paused`, `done`, and `terminated`. `active` workflows process signals and scheduled wakeups, `paused` workflows wait for resume or terminate, and terminal workflows stop accepting new work.

## 5. Agent And Tool Split

LLM activities decide what should happen and return structured data. Tool calls are executed by the workflow as separate Temporal activities so each external action has its own retry policy, timeout, and history entry.

## 8. Read Model

Postgres is a mirror for listing and historical reads. The workflow remains the source of truth while running; persistence activities append inbound records to `events`, append outbound decisions/actions to `actions`, and update the current `runs` row.

## 9. Failure Notes

Tool failures are captured as timeline entries so the workflow can continue. Persistence is retried by Temporal; if it still fails, the workflow keeps pending entries in memory and retries on the next snapshot instead of crashing the workflow.
