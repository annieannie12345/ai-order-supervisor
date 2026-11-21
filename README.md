# AI Order Supervisor

An event-driven, LLM-powered order supervisor built on **Temporal**, **FastAPI**, and **Postgres**. Each order gets one long-lived `OrderSupervisorWorkflow` that wakes on start, on external events (signals), or on a self-scheduled timer — runs an agent step — and goes back to sleep.

## Final Demo Video

[Watch the final demo video](./Final_video.mp4)

---

## Submission Quick Start

This is the recommended way to run the full submitted project locally.

### Prerequisites

- Docker or Colima
- Ollama running locally
- Ollama model: `qwen2.5:7b-instruct`

Verify the local model:

```bash
ollama list
curl http://localhost:11434/api/tags
```

### Start The Project

Run these commands from the project root:

```bash
cd /Users/anishagupta/Desktop/backend
cp .env.example .env
colima start
docker compose --env-file .env up -d --build
docker compose --env-file .env ps -a
```

Expected status:

```text
postgres      healthy
temporal      healthy
temporal-ui   healthy
backend       healthy
worker        healthy
frontend      healthy
migrate       exited 0
```

Open:

- Frontend: http://localhost:3000
- Backend API docs: http://localhost:8000/docs
- Temporal UI: http://localhost:8233

### Seed Demo Data

For a simple dashboard demo:

```bash
docker compose --env-file .env exec backend python -m scripts.demo_data
```

Expected output:

```text
Seeded demo data: 3 supervisors, 10 runs.
```

For a richer dashboard/demo dataset:

```bash
docker compose --env-file .env exec backend python -m scripts.reset_demo_data
docker compose --env-file .env exec backend python -m scripts.seed_demo_data --runs 25
```

### Stop The Project

```bash
docker compose --env-file .env down
```

To also remove local Postgres data:

```bash
docker compose --env-file .env down -v
```

### Submission Documents

- `ARCHITECTURE_NOTE.md` - short architecture overview

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

### Data Model

Postgres stores four core tables:

- `supervisors` - agent instructions, tools, wake policy, and model config
- `runs` - order workflow status and Temporal workflow ID
- `events` - incoming payment, shipment, refund, and customer events
- `actions` - agent decisions, tool calls, memory updates, wakeups, and final summaries

### Workflow Behavior

Each order has one Temporal workflow. The workflow starts active, processes important events, can sleep until the next wakeup, and can be interrupted, resumed, or terminated from the UI.

Routine events are logged to the timeline. Important events, such as shipment delays or refund requests, wake the agent and may trigger tool actions.

### Key Design Choices

- One workflow per order keeps each order isolated and easy to inspect in Temporal.
- FastAPI stays stateless; Temporal owns live workflow state and Postgres stores the dashboard read model.
- Tool calls are Temporal activities, so they are retryable and visible in workflow history.
- The frontend shows a readable timeline instead of raw JSON and locks controls while the agent is processing.

For more detail, see `ARCHITECTURE_NOTE.md`.
