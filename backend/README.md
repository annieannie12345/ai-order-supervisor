# AI Order Supervisor

An event-driven, LLM-powered order supervisor built on **Temporal**, **FastAPI**, and **Postgres**. Each order gets one long-lived `OrderSupervisorWorkflow` that wakes on start, on external events (signals), or on a self-scheduled timer — runs an agent step — and goes back to sleep.

---

## 1. Architecture Overview

```
Next.js UI  ──HTTP──►  FastAPI  ──Temporal Client──►  OrderSupervisorWorkflow (per order_id)
                          │                                   │
                          ▼                                   ▼
                      Postgres (mirror/read model)     Activities (LLM, tools, persistence)
```

- **FastAPI** is a thin, stateless shell: it starts workflows, sends signals, and runs queries. It never holds business state itself.
- **`OrderSupervisorWorkflow`** is a single durable coroutine per order (workflow ID: `order-supervisor-{order_id}`), running from `order_created` to a terminal state (`delivered`, `cancelled`, `refunded`, or manual termination).
- **Activities** do all non-deterministic work — LLM calls, mocked tool effects, and Postgres writes — keeping the workflow itself deterministic and replay-safe.
- **Postgres** is a read-model mirror only. It's updated by activities and lets `GET /runs` list views avoid querying every open workflow.

### Why one workflow handles all three wake triggers

Temporal workflows are durable coroutines, so "wake on start / signal / schedule" maps directly onto a single `while not terminal:` loop with one `workflow.wait_condition()` wait point:

- **start** → the top of `run()`
- **signal** → `wait_condition()` unblocks because a signal handler mutated state
- **scheduled wake-up** → `wait_condition()` unblocks via timeout (a durable Temporal timer, so it survives worker restarts)

### Memory & timeline compaction

- `timeline`: an append-only list of recent events/actions; only the last ~20 entries go into each agent prompt. Full history is persisted to Postgres.
- `memory_summary`: a short rolling text blob the agent rewrites every step (old summary + new events → new ≤300-word summary). This is the compaction strategy — no separate summarization pass needed.
- `continue_as_new` fires once the in-memory timeline reaches the configured threshold, carrying over `order_ctx`, `memory_summary`, `status`, `extra_instructions`, the current wake time, and the last timeline entries used for prompting.

### Postgres schema (read model)

```sql
supervisors(id, name, base_instruction, tools jsonb, wake_policy jsonb, model_config jsonb)
runs(id, order_id, supervisor_id, workflow_id, status, next_wake_at, created_at, updated_at)
events(id, run_id, ts, type, payload jsonb, important boolean)
actions(id, run_id, ts, type, payload jsonb)
```

`events` = everything that came in. `actions` = everything the agent did or decided (`tool_call`, `memory_updated`, `wake_scheduled`, `final_summary`). Current memory and final summary are both *derived* — just the latest row of the relevant `type`, not separate mutable tables.

### Project layout

```
.
├── main.py                    # FastAPI app entrypoint
├── worker.py                  # Temporal worker entrypoint
├── client.py                  # Shared Temporal client factory
├── config.py                  # Settings (env-driven)
├── api/
│   ├── routers/
│   │   ├── runs.py
│   │   └── supervisors.py
│   └── deps.py
├── workflows/
│   └── order_supervisor.py    # OrderSupervisorWorkflow
├── activities/
│   ├── agent.py                # classify_event_importance, run_agent_step, generate_final_summary
│   ├── tools.py                 # 6 mocked tool activities
│   └── persistence.py           # persist_snapshot
├── shared/
│   ├── constants.py             # TASK_QUEUE, etc.
│   └── dataclasses.py           # SupervisorInput, OrderEvent, AgentStepInput, ...
├── db/
│   └── session.py               # SQLAlchemy engine/session, dispose_engine
├── scripts/
│   └── event_generator.py       # Standalone script to signal a running workflow
└── alembic/                    # Database migrations
```

---

## 2. Setup

### Docker Compose quickstart

From the parent folder that contains both `backend/` and
`order-supervisor-frontend/`:

```bash
cd /Users/anishagupta/Desktop/backend
docker compose up --build
```

This starts Postgres, Temporal, Temporal UI, FastAPI, the Temporal worker,
and the Next.js frontend.

- Frontend: `http://localhost:3000`
- FastAPI: `http://localhost:8000`
- FastAPI docs: `http://localhost:8000/docs`
- Temporal UI: `http://localhost:8233`

If `OPENAI_API_KEY` is not set, the POC uses the deterministic local agent
fallback so the end-to-end workflow still runs for demos.

### Prerequisites

- Python 3.11+
- Docker (for local Postgres and/or Temporal dev server) or a Temporal Cloud account
- [Temporal CLI](https://docs.temporal.io/cli) (`temporal` command) for local dev

### Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure environment

Create a `.env` file (loaded via `config.py`'s `settings`):

```bash
# Temporal
TEMPORAL_TARGET_HOST=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TLS_ENABLED=false
# TEMPORAL_TLS_CLIENT_CERT=...
# TEMPORAL_TLS_CLIENT_KEY=...

# Worker tuning
WORKER_MAX_CONCURRENT_ACTIVITIES=40
WORKER_MAX_CONCURRENT_WORKFLOW_TASKS=20

# Postgres
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/order_supervisor
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=20

# CORS
CORS_ALLOW_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000","http://localhost:3001","http://127.0.0.1:3001"]
```

---

## 3. Running Postgres

Local dev via Docker:

```bash
docker run --name order-supervisor-pg \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=order_supervisor \
  -p 5432:5432 \
  -d postgres:16
```

Apply the schema with Alembic:

```bash
alembic upgrade head
```

---

## 4. Running the Temporal Server

For local development, use the Temporal CLI's built-in dev server (includes Web UI on `:8233`):

```bash
temporal server start-dev
```

For Temporal Cloud, set `TEMPORAL_TARGET_HOST`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TLS_ENABLED=true`, and the mTLS cert/key env vars instead.

---

## 5. Running the Temporal Worker

The worker registers `OrderSupervisorWorkflow` plus every activity from `activities/agent.py`, `activities/tools.py`, and `activities/persistence.py`, then polls the configured task queue until `SIGINT`/`SIGTERM`.

```bash
python worker.py
```

You should see a log line confirming the task queue, namespace, and counts of registered workflows/activities. Run multiple worker processes for horizontal scaling — they share the same task queue.

---

## 6. Running FastAPI

```bash
uvicorn main:app --reload --port 8000
```

On startup, `main.py`'s lifespan handler eagerly connects to Temporal (so the app fails fast at boot rather than surfacing a connection error on a random first request) and tears the client down cleanly on shutdown.

- Health check: `GET http://localhost:8000/health`
- Interactive docs: `http://localhost:8000/docs`

---

## 7. Running the Event Generator

`scripts/event_generator.py` is a standalone script that uses the same `client.py` factory to signal a running workflow from outside the request/response cycle — useful for simulating order lifecycle events (payment received, shipment update, customer message, etc.) without wiring up real upstream integrations.

```bash
python -m scripts.event_generator ORD-12345 shipment_delayed \
  --new-eta 2026-07-10T12:00:00+00:00 --reason "weather"
```

The script sends a single `submit_event` signal for the event type you choose, so you can watch the workflow classify, decide, and act in the Temporal Web UI.

---

## 8. API Examples

### Start a run

```bash
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
        "order_id": "ORD-12345",
        "supervisor_id": "default",
        "order_payload": {
          "customer_name": "Jane Doe",
          "items": [{"sku": "ABC-1", "qty": 1}],
          "status": "placed"
        }
      }'
```

Maps to `start_workflow(OrderSupervisorWorkflow.run, ...)` with workflow ID `order-supervisor-ORD-12345`. If a run for that order already exists, `WorkflowAlreadyStartedError` is caught and the existing run is returned instead of erroring.

### Submit an event

```bash
curl -X POST http://localhost:8000/runs/<run_id>/events \
  -H "Content-Type: application/json" \
  -d '{"type": "shipment_delayed", "payload": {"new_eta": "2026-07-10"}}'
```

Sends the `submit_event` signal; the workflow queues it, runs it through `classify_event_importance`, and triggers a full agent step if it's deemed important (or if there are pending manual instructions).

### Add a manual instruction

```bash
curl -X POST http://localhost:8000/runs/ORD-12345/instructions \
  -H "Content-Type: application/json" \
  -d '{"instruction": "Offer a 10% discount if the customer complains about the delay."}'
```

### Interrupt / resume / terminate

```bash
curl -X POST http://localhost:8000/runs/ORD-12345/interrupt
curl -X POST http://localhost:8000/runs/ORD-12345/resume
curl -X POST http://localhost:8000/runs/ORD-12345/terminate
```

### Get current state

```bash
curl http://localhost:8000/runs/ORD-12345
```

Runs a live `query(get_state)` against the workflow if it's still open; falls back to the Postgres mirror (`runs`/`events`/`actions` tables) if the workflow has already closed.

### Get the timeline

```bash
curl http://localhost:8000/runs/ORD-12345/timeline
```

Backed by `(SELECT ... FROM events) UNION ALL (SELECT ... FROM actions) ORDER BY ts`.

---

## 9. Design Decisions

- **One workflow per order, not per supervisor or globally.** This gives natural isolation, a free idempotency key (`order-supervisor-{order_id}` + `WorkflowIDReusePolicy`), and lets each order's history/replay be inspected independently in the Temporal Web UI.
- **FastAPI holds no business state.** All state lives in the workflow (source of truth while running) and Postgres (durable read model / history after completion). This keeps FastAPI horizontally scalable and trivially restartable.
- **A single `wait_condition` drives the whole loop.** Rather than separate code paths for "signal received" vs. "timer fired," both conditions feed one `wait_condition(..., timeout=...)` call — mirroring how Temporal timers and signal-driven wakeups are really the same mechanism (a coroutine unblocking).
- **A cheap classifier gates expensive agent steps.** Every inbound event is classified for importance before deciding whether to run the (comparatively expensive) main agent step — this keeps LLM spend proportional to what actually matters rather than reacting to every minor event.
- **Tool calls run as separate activities from the workflow**, rather than being executed inside `run_agent_step` itself. This costs a couple of extra round trips but gives much better observability/history per tool call in the Temporal UI — worth it for a project this size.
- **Memory compaction is agent-driven, not a separate pipeline.** The agent rewrites its own rolling summary as part of its structured output on every step, avoiding a second summarization pass or extra infrastructure.
- **Postgres tables are minimal by design (4, not 5+).** `events` and `actions` are the only append-only logs; "current memory" and "final summary" are derived as the latest row of a given `type`, rather than modeled as separate mutable tables that could drift out of sync.
- **`continue_as_new` on a simple counter (`event_seq >= 200`).** Keeps Temporal workflow history bounded without needing more elaborate size-based heuristics for a project this scope; full history is safely preserved in Postgres regardless.
- **Retries are capped on tool activities.** A flaky mocked tool logs a `tool_failed` timeline entry and lets the agent decide the next step, rather than letting a stuck activity retry indefinitely or crash the workflow.
