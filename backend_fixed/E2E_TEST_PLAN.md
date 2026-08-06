# AI Order Supervisor E2E Test Plan

Scope: validate the complete path `Postgres -> Temporal -> Worker -> FastAPI -> Next.js frontend` for the existing AI Order Supervisor system.

Related apps:
- Backend: `/Users/anishagupta/Desktop/backend/backend_fixed`
- Frontend: `/Users/anishagupta/Desktop/backend/order-supervisor-frontend`
- Docker Compose: `/Users/anishagupta/Desktop/backend/docker-compose.yml`

## 1. Ordered Testing Sequence

1. Start the full stack with `docker compose up --build` from `/Users/anishagupta/Desktop/backend`.
2. Verify service readiness:
   - FastAPI health: `GET http://localhost:8000/health` returns `{"status":"ok"}`.
   - Frontend loads at `http://localhost:3000`.
   - Temporal UI loads at `http://localhost:8233`.
   - Postgres accepts connections and Alembic migration has run.
3. Create 5 supervisors through the frontend and verify them through `GET /supervisors`.
4. Create 10 runs from those supervisors and verify:
   - `runs` rows exist in Postgres.
   - Temporal workflows exist with workflow ids `order-supervisor-{order_id}`.
   - Worker executes initial `workflow_start` agent step.
   - Timeline shows `agent_action`, `memory_updated`, and expected tool/wake entries.
5. Submit events for active runs:
   - `payment_received`
   - `shipment_created`
   - `customer_message`
   - `refund_requested`
6. Validate event classification and persistence:
   - Event appears in live timeline as `event:{event_type}`.
   - Postgres `events.type` is `order_event`, with `payload.event_type` preserving business type.
   - Important events wake the agent where expected.
7. Validate workflow controls:
   - Add instruction.
   - Interrupt.
   - Resume.
   - Terminate.
8. Validate timeline consistency in frontend, API, Temporal queries, and Postgres.
9. Validate terminal behavior:
   - Done/terminated runs reject new events, instructions, interrupt, resume, and terminate where applicable with `409`.
   - Read endpoints fall back to Postgres mirror after workflow closure.
10. Run frontend smoke/integration checks:
   - Dashboard list, search, filter.
   - Create run form validation.
   - Supervisor create and revised-template behavior.
   - Run details polling and manual refresh.

## 2. API Surface To Validate

Health:
- `GET /health`

Supervisors:
- `POST /supervisors`
- `GET /supervisors`
- `GET /supervisors/{supervisor_id}`

Runs:
- `POST /runs`
- `GET /runs`
- `GET /runs?run_status={active|paused|done|terminated}`
- `GET /runs?order_id={order_id}`
- `GET /runs?limit={1..200}&offset={n}`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/timeline`
- `POST /runs/{run_id}/events`
- `POST /runs/{run_id}/instructions`
- `POST /runs/{run_id}/interrupt`
- `POST /runs/{run_id}/resume`
- `POST /runs/{run_id}/terminate`

Important contract note: there is no backend update endpoint for supervisors. The frontend “Edit supervisor draft” flow intentionally creates a revised supervisor template instead of modifying the existing supervisor id.

## 3. Temporal Surface To Validate

Workflow:
- `OrderSupervisorWorkflow.run`
- Workflow id: `order-supervisor-{order_id}`
- Task queue: `order-supervisor`

Signals:
- `submit_event(OrderEvent)`
- `add_instruction(str)`
- `interrupt()`
- `resume()`
- `terminate()`

Queries:
- `get_state()`
- `get_timeline()`
- `get_memory()`

Workflow transitions:
- `workflow_start -> active`
- `active -> active` after routine event persistence
- `active -> active` after important event wakes agent
- `active -> paused` after interrupt
- `paused -> active` after resume
- `active|paused -> terminated` after terminate
- `active -> done` when agent closes workflow
- `active -> active` after scheduled wakeup
- `active -> continue_as_new -> active` when timeline reaches threshold
- `activity failure -> paused` when agent fails after retries

## 4. Manual E2E Checklist

### A. Supervisor Management

Create supervisor
- Preconditions: stack is running; frontend reachable; backend health is ok.
- Steps: open `/supervisors`; fill name, base instruction, select tools, enter valid JSON wake policy and model config; click `Create supervisor`.
- Expected result: new supervisor appears in Templates list; count increases; `GET /supervisors` returns the supervisor; secret config keys such as `api_key` are redacted in responses.

Edit supervisor / revised template
- Preconditions: at least one supervisor exists.
- Steps: select a supervisor in Templates; confirm form title is `Edit supervisor draft`; change name/instruction; click `Save revised template`.
- Expected result: a new supervisor is created with a new id; original supervisor remains unchanged; list count increases by 1; no `PUT/PATCH` request is expected.

List supervisors
- Preconditions: multiple supervisors exist.
- Steps: open `/supervisors`; call `GET /supervisors`.
- Expected result: UI list matches API response; backend orders supervisors by name; each item shows correct name and tool count.

### B. Run Lifecycle

Create run
- Preconditions: at least one supervisor exists; worker is polling task queue.
- Steps: open `/runs/new`; select supervisor; enter unique `order_id`; submit valid order payload; click `Start workflow`.
- Expected result: browser navigates to `/runs/{run_id}`; `POST /runs` returns `201`; Postgres has `runs.status=active`; Temporal UI shows workflow `order-supervisor-{order_id}`; timeline eventually contains `agent_action` and `memory_updated`.

Create duplicate run
- Preconditions: a run exists for `order_id`.
- Steps: submit another run with the same `order_id`.
- Expected result: API returns `409`; frontend shows backend error; no duplicate `runs.order_id` row is created.

View run
- Preconditions: a run exists.
- Steps: open dashboard; click Details; inspect status, next wake, memory summary, timeline.
- Expected result: `GET /runs/{run_id}` reflects live Temporal query while active; timeline order is newest-first in UI; manual Refresh and 5-second polling update state.

Run state updates
- Preconditions: active run exists.
- Steps: submit instruction/event/control signals and watch details page.
- Expected result: status badge, memory summary, next wake, and timeline converge with API responses after polling.

### C. Event Processing

payment_received
- Preconditions: active run exists.
- Steps: submit event type `payment_received` with amount, currency, payment method, transaction id.
- Expected result: API returns `202` with temporary `id=-1`; timeline later includes `event:payment_received`; Postgres stores `events.type=order_event`, `payload.event_type=payment_received`; deterministic fallback classifies it routine, but agent may add internal note when awakened by another signal.

shipment_created
- Preconditions: active run exists.
- Steps: submit event type `shipment_created` with carrier, tracking number, estimated delivery.
- Expected result: timeline includes `event:shipment_created`; event persists; deterministic agent may create internal note if the event is processed in an agent step; UI displays payload JSON without corruption.

customer_message
- Preconditions: active run exists.
- Steps: submit event type `customer_message` with message and channel.
- Expected result: event is classified important; workflow wakes; timeline includes `event:customer_message`, `agent_action`, `tool:send_customer_message`, and likely `tool:create_internal_note`; memory summary mentions customer contact.

refund_requested
- Preconditions: active run exists with `close_workflow` tool enabled if terminal flow is being tested.
- Steps: submit event type `refund_requested` with amount, currency, reason.
- Expected result: event is classified important; workflow wakes; timeline includes escalation/review tool calls when tools are enabled; deterministic fallback sets close workflow, then final summary runs; status becomes `done` or `terminated` depending on control path.

### D. Workflow Controls

Add instruction
- Preconditions: active or paused non-terminal run exists.
- Steps: enter instruction in Run Details and click `Add instruction`.
- Expected result: API returns `202`; timeline includes `instruction_added`; active workflow wakes and runs agent; instruction appears in memory/action context; Postgres stores event row type `instruction_added`.

Interrupt
- Preconditions: active non-terminal run exists.
- Steps: click `Interrupt`.
- Expected result: API returns `202`; status becomes `paused`; timeline includes `interrupted`; Postgres run status eventually becomes `paused`; while paused, routine events are queued but not processed until resume or terminate.

Resume
- Preconditions: paused run exists.
- Steps: click `Resume`.
- Expected result: API returns `202`; status becomes `active`; timeline includes `resumed`; workflow wakes with reason `signal`; queued events are processed.

Terminate
- Preconditions: active or paused non-terminal run exists.
- Steps: click `Terminate`.
- Expected result: API returns `202`; timeline includes `terminate_requested`, `final_summary`, and `terminated`; status becomes `terminated`; subsequent event/instruction/control requests return `409`.

### E. Timeline Validation

Event persistence
- Preconditions: run has received at least one order event and one control signal.
- Steps: compare `GET /runs/{run_id}/timeline`, Temporal `get_timeline`, and Postgres `events`.
- Expected result: live timeline contains business kinds such as `event:refund_requested`; DB event rows use enum types `order_event`, `instruction_added`, `interrupt`, `resume`, `terminate`; business event type is preserved in payload.

Action persistence
- Preconditions: workflow has completed at least one agent step.
- Steps: inspect timeline and Postgres `actions`.
- Expected result: action rows use enum types `agent_action`, `memory_updated`, `tool_call`, `tool_failed`, `wake_scheduled`, `final_summary`, or `lifecycle`; tool timeline entries normalize to `tool_call` in DB and keep the tool name in payload.

Status updates
- Preconditions: run has moved through active, paused, active, terminated/done.
- Steps: compare dashboard row, run details status, `GET /runs`, `GET /runs/{run_id}`, Temporal state query, and Postgres `runs.status`.
- Expected result: all surfaces converge; active live reads prefer Temporal; terminal reads fall back to Postgres mirror.

## 5. Integration Test Cases

API tests
- Health returns `200`.
- Create supervisor accepts valid payload and returns redacted `model_config` secrets.
- Create supervisor rejects invalid JSON at frontend validation level; API rejects schema-invalid JSON with `422`.
- List/get supervisor returns created records; unknown supervisor returns `404`.
- Create run with unknown supervisor returns `404`.
- Create run with duplicate order id returns `409`.
- List runs supports status, order id, limit, and offset.
- Get unknown run returns `404`.
- Submit event to active run returns `202` and accepted echo.
- Submit event to terminal run returns `409`.
- Add instruction to active run returns `202`.
- Interrupt/resume/terminate active run return `202`.
- Re-control terminal run returns `409`.
- Timeline endpoint returns chronologically sorted entries from API; frontend reverses for display.

Backend integration tests
- Postgres migration creates native enums and indexes.
- `POST /runs` commits run row before workflow start.
- Worker registers workflow and all 10 activities.
- Initial workflow step persists snapshot without enum mapping errors.
- `persist_snapshot` maps `event:*` to `events.type=order_event`.
- `persist_snapshot` maps control events to `instruction_added`, `interrupt`, `resume`, `terminate`.
- `persist_snapshot` maps `tool:*` to `actions.type=tool_call`.
- Temporal query fallback works after terminal workflow closure.
- Deterministic no-key agent path works without `OPENAI_API_KEY`.
- Scheduled wakeups set `runs.next_wake_at` and timeline `wake_scheduled`.
- Activity retry does not leave run permanently inconsistent after transient worker restart.

Frontend integration tests
- Dashboard renders backend-unavailable empty state when API is down.
- Dashboard counts active, paused, scheduled runs correctly.
- Dashboard search matches order id, run id, and workflow id.
- Status filter shows active, paused, done, terminated.
- Create run form requires supervisor and valid JSON object payload.
- Create run success redirects to details page and invalidates runs query.
- Run details polls state and timeline every 5 seconds.
- Manual Refresh refetches state and timeline.
- Submit event form swaps payload template when event type changes.
- Submit event rejects invalid JSON object before API call.
- Add instruction rejects blank/too-short instruction before API call.
- Interrupt/resume/terminate optimistically update dashboard cache and then reconcile with backend.
- Supervisor form requires name, instruction, at least one tool, and JSON object configs.
- Selecting supervisor resets form into revised-template mode and save creates a new template.

## 6. Test Data

Use these supervisors unless testing secret redaction; for redaction add `api_key` to `model_config` and verify response value is `********`.

```json
[
  {
    "name": "Fulfillment Control",
    "base_instruction": "Monitor fulfillment, shipment creation, delivery delays, and carrier exceptions. Keep customers informed and escalate severe shipment issues.",
    "tools": ["create_internal_note", "send_customer_message", "schedule_next_wakeup", "mark_for_review"],
    "wake_policy": {"aggressiveness": "balanced", "default_check_hours": 6},
    "model_config": {"model": "gpt-4o-mini", "temperature": 0.2}
  },
  {
    "name": "Payments And Refunds",
    "base_instruction": "Track payment capture, failed payments, refund requests, and chargeback-risk orders. Escalate financial exceptions to a human.",
    "tools": ["create_internal_note", "escalate_issue", "mark_for_review", "close_workflow"],
    "wake_policy": {"aggressiveness": "high", "default_check_hours": 2},
    "model_config": {"model": "gpt-4o-mini", "temperature": 0.1}
  },
  {
    "name": "VIP Customer Care",
    "base_instruction": "Prioritize customer-facing issues for VIP orders. Respond quickly to customer messages and create internal notes for support.",
    "tools": ["send_customer_message", "create_internal_note", "escalate_issue", "schedule_next_wakeup"],
    "wake_policy": {"aggressiveness": "high", "default_check_hours": 1},
    "model_config": {"model": "gpt-4o", "temperature": 0.2}
  },
  {
    "name": "Returns Specialist",
    "base_instruction": "Handle returns, refund intent, replacement orders, and policy review. Close workflows only after a final summary is created.",
    "tools": ["create_internal_note", "mark_for_review", "escalate_issue", "close_workflow"],
    "wake_policy": {"aggressiveness": "balanced", "default_check_hours": 4},
    "model_config": {"model": "gpt-4o-mini", "temperature": 0}
  },
  {
    "name": "Low Touch Monitor",
    "base_instruction": "Log routine order events and wake only for customer-impacting changes, refund requests, failures, or explicit instructions.",
    "tools": ["create_internal_note", "schedule_next_wakeup"],
    "wake_policy": {"aggressiveness": "low", "default_check_hours": 12},
    "model_config": {"model": "gpt-4o-mini", "temperature": 0.1}
  }
]
```

Sample runs:

```json
[
  {"order_id": "QA-ORD-1001", "supervisor": "Fulfillment Control", "initial_memory": "New order awaiting shipment.", "order_payload": {"customer_name": "Jane Miller", "email": "jane.miller@example.com", "tier": "standard", "items": [{"sku": "BAG-100", "qty": 1, "name": "Everyday Tote"}], "status": "placed", "total": 49.99, "currency": "USD"}},
  {"order_id": "QA-ORD-1002", "supervisor": "Payments And Refunds", "initial_memory": "Payment is pending capture.", "order_payload": {"customer_name": "Rafael Chen", "email": "rafael.chen@example.com", "tier": "standard", "items": [{"sku": "SHOE-220", "qty": 1, "name": "Trail Runner"}], "status": "payment_pending", "total": 129.5, "currency": "USD"}},
  {"order_id": "QA-ORD-1003", "supervisor": "VIP Customer Care", "initial_memory": "VIP customer requested proactive updates.", "order_payload": {"customer_name": "Amara Singh", "email": "amara.singh@example.com", "tier": "vip", "items": [{"sku": "WATCH-9", "qty": 1, "name": "Field Watch"}], "status": "placed", "total": 299, "currency": "USD"}},
  {"order_id": "QA-ORD-1004", "supervisor": "Returns Specialist", "initial_memory": "Customer may request return if shipment misses event date.", "order_payload": {"customer_name": "Noah Brooks", "email": "noah.brooks@example.com", "tier": "standard", "items": [{"sku": "JKT-77", "qty": 1, "name": "Rain Jacket"}], "status": "processing", "total": 88.75, "currency": "USD"}},
  {"order_id": "QA-ORD-1005", "supervisor": "Low Touch Monitor", "initial_memory": "", "order_payload": {"customer_name": "Lina Torres", "email": "lina.torres@example.com", "tier": "standard", "items": [{"sku": "MUG-12", "qty": 2, "name": "Ceramic Mug"}], "status": "placed", "total": 31.98, "currency": "USD"}},
  {"order_id": "QA-ORD-1006", "supervisor": "Fulfillment Control", "initial_memory": "Shipment label is expected today.", "order_payload": {"customer_name": "Owen Patel", "email": "owen.patel@example.com", "tier": "standard", "items": [{"sku": "LAMP-4", "qty": 1, "name": "Desk Lamp"}], "status": "processing", "total": 64.2, "currency": "USD"}},
  {"order_id": "QA-ORD-1007", "supervisor": "Payments And Refunds", "initial_memory": "High-value order; verify payment and fraud signals.", "order_payload": {"customer_name": "Maya Johnson", "email": "maya.johnson@example.com", "tier": "vip", "items": [{"sku": "BIKE-55", "qty": 1, "name": "Commuter Bike"}], "status": "payment_pending", "total": 899, "currency": "USD"}},
  {"order_id": "QA-ORD-1008", "supervisor": "VIP Customer Care", "initial_memory": "Customer previously complained about delayed updates.", "order_payload": {"customer_name": "Ethan Kim", "email": "ethan.kim@example.com", "tier": "vip", "items": [{"sku": "HEADSET-8", "qty": 1, "name": "Noise Cancelling Headset"}], "status": "placed", "total": 179.99, "currency": "USD"}},
  {"order_id": "QA-ORD-1009", "supervisor": "Returns Specialist", "initial_memory": "Replacement may be needed if package arrives damaged.", "order_payload": {"customer_name": "Sofia Garcia", "email": "sofia.garcia@example.com", "tier": "standard", "items": [{"sku": "GLASS-6", "qty": 4, "name": "Glassware Set"}], "status": "shipped", "total": 72, "currency": "USD"}},
  {"order_id": "QA-ORD-1010", "supervisor": "Low Touch Monitor", "initial_memory": "Routine monitoring only.", "order_payload": {"customer_name": "Daniel Evans", "email": "daniel.evans@example.com", "tier": "standard", "items": [{"sku": "BOOK-15", "qty": 3, "name": "Cookbook"}], "status": "placed", "total": 54, "currency": "USD"}}
]
```

Realistic events:

```json
[
  {"type": "payment_received", "payload": {"amount": 49.99, "currency": "USD", "payment_method": "card", "transaction_id": "txn_qa_1001"}},
  {"type": "shipment_created", "payload": {"carrier": "UPS", "tracking_number": "1ZQA1001000001", "estimated_delivery": "2026-07-10T18:00:00+00:00"}},
  {"type": "customer_message", "payload": {"message": "Can someone confirm whether this will arrive before Friday?", "channel": "email", "customer_sentiment": "concerned"}},
  {"type": "refund_requested", "payload": {"amount": 88.75, "currency": "USD", "reason": "Order will arrive too late for planned trip"}},
  {"type": "payment_failed", "payload": {"amount": 129.5, "currency": "USD", "reason": "card_declined", "attempt": 1}},
  {"type": "shipment_delayed", "payload": {"carrier": "FedEx", "tracking_number": "FDXQA2002", "new_estimated_delivery": "2026-07-12T21:00:00+00:00", "reason": "weather"}},
  {"type": "order_delivered", "payload": {"carrier": "UPS", "tracking_number": "1ZQA1001000001", "delivered_at": "2026-07-10T16:35:00+00:00", "signed_by": "J Miller"}},
  {"type": "cancellation_requested", "payload": {"reason": "Changed mind", "requested_at": "2026-07-04T10:15:00+00:00"}}
]
```

## 7. Expected Outcomes

- Every accepted run creates exactly one Postgres run row and one Temporal workflow with matching workflow id.
- Worker processes initial start and signal-driven wakeups without stuck workflows.
- API read models and live workflow queries converge within polling/retry windows.
- Timeline entries preserve ordering, payload JSON, timestamps, event importance, and action details.
- Frontend never shows a permanently stale status after mutations; cache invalidation reconciles optimistic state.
- Terminal runs are protected from additional events or controls.
- Deterministic no-key mode allows repeatable local E2E without paid LLM calls.

## 8. Pass/Fail Criteria

Pass:
- All services start cleanly and remain healthy through the test run.
- 5 supervisors and 10 runs can be created through the UI/API.
- Each required event and control produces the expected Temporal, API, Postgres, and frontend state.
- No unhandled 500s appear in backend logs during happy-path tests.
- Temporal workflows do not remain stuck in pending workflow task/activity task states.
- UI state converges after manual refresh or within the 5-second polling interval.

Fail:
- Any API endpoint returns incorrect status code or malformed response for a covered case.
- Any accepted event/control is missing from both live timeline and Postgres after worker processing.
- Run status differs permanently between dashboard, details page, API, Temporal query, and DB.
- Workflow remains active after successful terminate request.
- Terminal workflow accepts new events/instructions through API.
- Frontend creates duplicate stale rows, fails to invalidate cache, or shows success when backend rejected the mutation.

## 9. Potential Failure Points To Watch

- Stale React Query cache after create run, command run, submit event, or add instruction.
- Optimistic command status masking backend `409` or signal failure.
- Workflow not waking after important signal because worker is not polling the shared `order-supervisor` task queue.
- API and worker task queue drift.
- Initial workflow snapshot fails if run row was not committed before workflow start.
- Event accepted by API but not persisted because workflow has not drained pending events yet.
- Routine event logged but not persisted until a later wake; testers should distinguish queued signal from persisted timeline.
- Postgres enum mapping failures for action kinds such as `agent_action`, `tool:*`, `interrupted`, or `terminate_requested`.
- Serialization issues for dataclasses, datetime values, JSONB payloads, and Pydantic alias `model_config`.
- Timezone display mismatch: backend stores timezone-aware datetimes; frontend formats in browser locale.
- Duplicate order id conflicts from `runs.order_id` and `runs.workflow_id` unique constraints.
- Terminal fallback mismatch when live Temporal query fails or workflow is closed.
- Activity retries may double-insert events/actions because `persist_snapshot` has no idempotency token.
- Worker restart during persist or tool execution may expose retry/idempotency issues.
- Frontend event naming mismatch: UI templates use `payment_confirmed` and `customer_message_received`; requested QA cases should also manually test `payment_received` and `customer_message`.
- Supervisor edit expectation mismatch: save creates a revised template, not an in-place update.
- Secret redaction gaps in supervisor read responses.
- CORS or `NEXT_PUBLIC_API_BASE_URL` mismatch between browser and backend.
