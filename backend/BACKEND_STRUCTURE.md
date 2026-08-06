# Backend Structure

## 5. API Contracts

Pydantic schemas under `schemas/` define request and response DTOs for FastAPI. Routers should import schema types rather than exposing ORM models directly unless the schema explicitly mirrors the ORM field names.

## 7. Agent Step Shape

Agent steps return a memory summary, structured `actions_taken`, optional tool calls, an optional `next_wake_at`, and a close flag. The workflow executes tool calls and persists the resulting timeline.

## 8. Persistence Mapping

Inbound order events are stored in `events`. Workflow decisions, lifecycle markers, tool results, wake schedules, and failure markers are stored in `actions`.
