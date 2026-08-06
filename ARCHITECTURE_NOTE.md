# Architecture Note

AI Order Supervisor is an event-driven order monitoring system. It uses a long-running Temporal workflow for each order, FastAPI as the API layer, PostgreSQL as the read model, a worker process for workflow and activity execution, and a Next.js frontend for operators.

## Service Diagram

```text
Next.js Frontend
      |
      | HTTP
      v
FastAPI Backend
      |
      | Temporal client commands, signals, queries
      v
Temporal Server  <---- Worker Process
      |                  |
      | workflow state   | activities
      |                  v
      |            LLM + mocked tools
      |
      v
PostgreSQL read model
```

## Main Components

- `order-supervisor-frontend/`
  - Next.js UI for supervisors, runs, timeline, events, instructions, and workflow controls.
- `backend/main.py`
  - FastAPI app entrypoint.
- `backend/api/routers/supervisors.py`
  - Supervisor config endpoints.
- `backend/api/routers/runs.py`
  - Run lifecycle endpoints. Starts workflows, sends signals, and queries state.
- `backend/workflows/order_supervisor.py`
  - Temporal workflow. Owns durable order state, sleeps, wakes, processes signals, and terminates.
- `backend/worker.py`
  - Temporal worker entrypoint. Registers workflows and activities.
- `backend/activities/agent.py`
  - LLM-backed event classification, agent decisions, memory updates, and final summaries.
- `backend/activities/tools.py`
  - Mocked operational tools such as customer messages, internal notes, review flags, wake scheduling, escalation, and close workflow.
- `backend/activities/persistence.py`
  - Persists workflow snapshots, events, and actions to Postgres.
- `backend/db/models.py`
  - SQLAlchemy models for supervisors, runs, events, and actions.

## Runtime Flow

1. An operator creates a supervisor config in the frontend.
2. The frontend calls FastAPI to create the supervisor row in Postgres.
3. The operator starts a run for an order.
4. FastAPI creates a run row and starts one Temporal workflow using workflow ID `order-supervisor-{order_id}`.
5. The workflow runs an initial agent step, persists timeline/actions, and schedules its next wakeup.
6. The workflow sleeps until:
   - a new event signal arrives,
   - an extra instruction signal arrives,
   - a resume/interrupt/terminate signal arrives, or
   - the scheduled wake timer fires.
7. The worker executes activities for LLM decisions, tools, and persistence.
8. The frontend reads current state and timeline through FastAPI.
9. Terminal workflows persist final summary and stop.

## State Ownership

- Temporal workflow state is the source of truth while a run is active.
- Postgres is the read model used for dashboard lists, timeline persistence, and historical data.
- FastAPI is intentionally stateless. It starts workflows, sends signals, and exposes queries.

## Workflow Signals And Queries

Signals:

- `submit_event`
- `add_instruction`
- `interrupt`
- `resume`
- `terminate`

Queries:

- `get_state`
- `get_timeline`

## Persistence Model

Postgres stores:

- `supervisors`: agent configuration
- `runs`: order run status and workflow ID
- `events`: inbound order/customer/payment/shipping events
- `actions`: outbound agent/tool/memory/final-summary actions

The timeline shown in the frontend is built from events and actions.

## Local LLM

The Docker setup is configured for Ollama through the OpenAI-compatible API:

```text
OPENAI_BASE_URL=http://host.docker.internal:11434/v1
OPENAI_API_KEY=ollama
LLM_MODEL=qwen2.5:7b-instruct
```

This keeps the demo local and avoids requiring a hosted API key.

## Design Tradeoffs

- One workflow per order keeps replay, isolation, idempotency, and Temporal UI inspection simple.
- Tool calls are separate activities, so they appear clearly in Temporal history and can be retried independently.
- The frontend locks controls while the agent is processing so the demo does not accept duplicate user actions.
- Current supervisor editing creates a revised supervisor config because the backend contract has create/list endpoints but no update endpoint.

