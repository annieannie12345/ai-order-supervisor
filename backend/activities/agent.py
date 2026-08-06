"""
activities/agent.py

LLM-backed activities for the OrderSupervisorWorkflow:

  * classify_event_importance — cheap/fast structured classification of an
    inbound OrderEvent; decides whether it's worth waking the main agent.
  * run_agent_step            — the main agent decision step. Builds a
    prompt from order context / memory / recent timeline / instructions,
    calls the model with tool-calling enabled, and returns a structured
    AgentStepResult (memory rewrite + tool calls + wake schedule + close
    flag).
  * generate_final_summary    — same shape as run_agent_step but prompted
    to produce a wrap-up pass (used for the "final_summary" reason before
    the workflow closes).

Design notes
------------
- All non-deterministic work (LLM calls) lives here, never in the workflow.
- We use an OpenAI-*compatible* async client (works against OpenAI, Azure
  OpenAI, or any provider exposing the /chat/completions or /responses
  contract) so the model/base_url can be swapped via SupervisorConfig
  .model_config without code changes.
- Structured output is enforced with Pydantic models passed as the
  `response_format` (OpenAI "Structured Outputs" / json_schema mode).
  Tool calls the agent wants to issue are NOT executed here — they are
  returned as data (list[ToolCall]) and executed by the workflow as
  separate activities, per ARCHITECTURE.md §5's revised design (cleaner
  history/observability).
- Every activity is a thin wrapper: build prompt -> call model -> validate
  -> map Pydantic result onto the shared dataclasses the workflow expects
  (AgentStepResult / ClassifyResult). Activities accept and return the
  same `shared.dataclasses` types used by the workflow so temporalio's
  default dataclass converter handles (de)serialization with no custom
  codec required.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator
from temporalio import activity

from shared.dataclasses import (
    AgentStepInput,
    AgentStepResult,
    ClassifyInput,
    ClassifyResult,
    ToolCall,
)

# --------------------------------------------------------------------- #
# Tool catalogue (OpenAI function-calling schemas)
#
# Names/args here must line up 1:1 with order_supervisor.py's
# _tool_activity_map and the six tool activities in activities/tools.py.
# --------------------------------------------------------------------- #

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "send_customer_message",
            "description": "Send a message directly to the customer about their order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Customer-facing message text."},
                },
                "required": ["message"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_internal_note",
            "description": "Leave an internal note on the order for other staff/agents. Not visible to the customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "Internal note text."},
                },
                "required": ["note"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_issue",
            "description": "Escalate this order to a human specialist/team for manual handling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Why this needs human escalation."},
                },
                "required": ["reason"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_for_review",
            "description": "Flag the order for asynchronous human review without a hard escalation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Why this order should be reviewed."},
                },
                "required": ["reason"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_next_wakeup",
            "description": (
                "Request that the workflow wake this agent up again at a specific "
                "future time (e.g. to check on shipment status)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "when": {
                        "type": "string",
                        "description": "ISO-8601 datetime (UTC) at which to wake up again.",
                    },
                },
                "required": ["when"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_workflow",
            "description": "Close out this order-supervision run permanently (e.g. delivered, cancelled, refunded).",
            "parameters": {
                "type": "object",
                "properties": {
                    "outcome": {
                        "type": "string",
                        "description": "Terminal outcome label, e.g. 'delivered', 'cancelled', 'refunded'.",
                    },
                },
                "required": ["outcome"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_NAMES = {t["function"]["name"] for t in TOOL_SCHEMAS}


# --------------------------------------------------------------------- #
# Pydantic schemas — structured LLM outputs
# --------------------------------------------------------------------- #

class ClassifyLLMOutput(BaseModel):
    """Structured output for the cheap importance classifier."""

    important: bool = Field(
        ..., description="True if this event warrants waking the main agent."
    )
    reasoning: str = Field(
        ..., description="One short sentence explaining the verdict."
    )


class ToolCallArg(BaseModel):
    name: Literal[
        "send_customer_message",
        "create_internal_note",
        "escalate_issue",
        "mark_for_review",
        "schedule_next_wakeup",
        "close_workflow",
    ]
    args: dict[str, Any] = Field(default_factory=dict)


class AgentDecision(BaseModel):
    """
    Structured output for the main agent step. The model may additionally
    emit native tool_calls (function-calling); this schema captures the
    *decision* fields that ride alongside/after those calls once the model
    is done calling tools for this turn.
    """

    updated_memory_summary: str = Field(
        ..., description="Rewritten rolling memory summary, <=300 words."
    )
    actions_taken: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form structured record of what happened this step, for the timeline.",
    )
    next_wake_at: datetime | None = Field(
        default=None,
        description="If set, when the agent should be woken again absent other signals.",
    )
    close_workflow: bool = Field(
        default=False, description="True if this order-supervision run should end."
    )

    @field_validator("next_wake_at")
    @classmethod
    def _normalize_next_wake_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


# --------------------------------------------------------------------- #
# Prompt builders
# --------------------------------------------------------------------- #

CLASSIFY_SYSTEM_PROMPT = """\
You are a fast, cheap importance classifier for an AI order-supervision agent.
Given an inbound order event and the agent's current memory of the order, decide
whether this event is important enough to wake the (slower, more expensive) main
agent right now, or whether it's safe to just log it and let the agent see it on
its next scheduled pass.

Wake the agent for: payment failures/refunds, shipment exceptions, delivery
failures, customer complaints or direct customer messages, cancellation
requests, fraud/risk flags, or anything the memory summary indicates the agent
is specifically watching for.

Do NOT wake the agent for: routine status pings that match the expected happy
path, duplicate/no-op events, or informational events with no action required.

Respond only with the structured fields requested."""


def build_classify_messages(input: ClassifyInput) -> list[dict[str, Any]]:
    user_payload = {
        "order_id": input.order_ctx.order_id,
        "order_payload": input.order_ctx.order_payload,
        "current_memory_summary": input.memory_summary,
        "event": {"type": input.event.type, "payload": input.event.payload},
    }
    return [
        {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, default=str)},
    ]


AGENT_SYSTEM_PROMPT_TEMPLATE = """\
You are an autonomous AI order-supervision agent responsible for a single order.

Base instructions for this supervisor role:
{base_instruction}

You may call any of the following tools when appropriate: {available_tools}.
Only call tools that are relevant this turn; calling no tools is a valid outcome.

You are being invoked because: {reason}.

After you are done calling any tools, respond with a final structured decision
containing:
- updated_memory_summary: a rewritten rolling summary (<=300 words) of
  everything relevant so far — merge your old summary with anything new from
  this step. This is your only persistent memory between steps; be concise
  but don't drop information you'll need later (open issues, promises made
  to the customer, wake-sensitivity guidance, etc.).
- actions_taken: a short structured record of what you decided/did this step.
- next_wake_at: an ISO-8601 UTC datetime if you want to be woken again at a
  specific time absent other signals, otherwise null. You may also call the
  schedule_next_wakeup tool; the workflow stores that tool's normalized
  datetime as the next wake time.
- close_workflow: true only if this order's supervision should end now
  (e.g. delivered & confirmed, cancelled, refunded, or otherwise terminal).
"""


def build_agent_messages(input: AgentStepInput) -> list[dict[str, Any]]:
    system = AGENT_SYSTEM_PROMPT_TEMPLATE.format(
        base_instruction=input.order_ctx.supervisor.base_instruction,
        available_tools=", ".join(input.available_tools) or "(none configured)",
        reason=input.reason,
    )
    user_payload = {
        "order_id": input.order_ctx.order_id,
        "order_payload": input.order_ctx.order_payload,
        "current_memory_summary": input.memory_summary,
        "recent_timeline": [
            {"ts": e.ts.isoformat(), "kind": e.kind, "payload": e.payload}
            for e in input.recent_timeline
        ],
        "extra_instructions": input.extra_instructions,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, default=str)},
    ]


FINAL_SUMMARY_SYSTEM_SUFFIX = """

This is the FINAL step for this order-supervision run. Do not call any tools
other than close_workflow if you haven't already closed the run. Your
updated_memory_summary for this step should instead be treated as a wrap-up:
summarize the outcome, key actions taken across the run, any learnings, and
recommendations for a human reviewing this later. Set close_workflow to true.
"""


def build_final_summary_messages(input: AgentStepInput) -> list[dict[str, Any]]:
    messages = build_agent_messages(input)
    messages[0]["content"] += FINAL_SUMMARY_SYSTEM_SUFFIX
    return messages


# --------------------------------------------------------------------- #
# Model client
# --------------------------------------------------------------------- #

def _client_for(model_config: dict[str, Any]) -> AsyncOpenAI:
    """
    Build an OpenAI-compatible async client from SupervisorConfig.model_config.
    Expected keys (all optional except relying on env defaults):
      - api_key
      - base_url   (point this at Azure OpenAI / any compatible gateway)
    """
    base_url = model_config.get("base_url") or os.getenv("OPENAI_BASE_URL")
    api_key = model_config.get("api_key") or os.getenv("OPENAI_API_KEY")
    if base_url and not api_key:
        # Ollama's OpenAI-compatible API requires an API key syntactically,
        # but it does not validate the value for local requests.
        api_key = "ollama"
    return AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
    )


def _model_name(model_config: dict[str, Any], default: str) -> str:
    return model_config.get("model") or os.getenv("LLM_MODEL") or default


def _should_use_deterministic_agent(model_config: dict[str, Any]) -> bool:
    return not (
        model_config.get("api_key")
        or model_config.get("base_url")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("OPENAI_BASE_URL")
    )


def _event_types_from_timeline(input: AgentStepInput) -> list[str]:
    return [
        entry.kind.removeprefix("event:")
        for entry in input.recent_timeline
        if entry.kind.startswith("event:")
    ]


def _deterministic_memory(input: AgentStepInput, note: str) -> str:
    events = _event_types_from_timeline(input)
    event_text = ", ".join(events[-6:]) if events else "no order events yet"
    base = input.memory_summary.strip()
    pieces = [
        f"Order {input.order_ctx.order_id} is being supervised.",
        f"Recent events: {event_text}.",
        note,
    ]
    if base:
        pieces.insert(1, f"Prior memory: {base}")
    if input.extra_instructions:
        pieces.append("Run instructions: " + " ".join(input.extra_instructions))
    return " ".join(pieces)


def _deterministic_tool_calls(input: AgentStepInput) -> list[ToolCall]:
    available = set(input.available_tools)
    events = set(_event_types_from_timeline(input))
    calls: list[ToolCall] = []

    def add(name: str, args: dict[str, Any]) -> None:
        if name in available:
            calls.append(ToolCall(name=name, args=args))

    if input.reason == "workflow_start":
        add("create_internal_note", {"note": "Started AI supervision for this order."})
        next_wake_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        add("schedule_next_wakeup", {"when": next_wake_at.isoformat()})
    if "customer_message" in events or "customer_message_received" in events:
        add("send_customer_message", {"message": "Thanks for the update. We are reviewing your order and will follow up shortly."})
        add("create_internal_note", {"note": "Customer message received and acknowledged by the supervisor."})
    if "refund_requested" in events:
        add("escalate_issue", {"reason": "Customer requested a refund; needs human review before resolution."})
        add("mark_for_review", {"reason": "Refund request requires policy and order-state review."})
    if "shipment_created" in events:
        add("create_internal_note", {"note": "Shipment was created; continue monitoring through delivery."})
    if "payment_received" in events or "payment_confirmed" in events:
        add("create_internal_note", {"note": "Payment confirmed for this order."})
    return calls


# --------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------- #

def _extract_tool_calls(message: Any) -> list[ToolCall]:
    """Map raw OpenAI tool_calls off a chat completion message to ToolCall dataclasses."""
    calls: list[ToolCall] = []
    for tc in getattr(message, "tool_calls", None) or []:
        name = tc.function.name
        if name not in TOOL_NAMES:
            continue
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        calls.append(ToolCall(name=name, args=args))
    return calls


async def _run_structured_agent_turn(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, Any]],
) -> tuple[AgentDecision, list[ToolCall]]:
    """
    Single-turn agent call: offer tools + ask for a structured final decision.
    Tool calls are returned as data (not executed here). If the model chose
    to call tools instead of returning the structured decision directly in
    this turn, we make one follow-up call (with the tool_calls acknowledged
    as pending/no-op results) purely to force the structured decision object,
    since tool execution itself happens in the workflow as separate
    activities.
    """
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        tools=TOOL_SCHEMAS,
        tool_choice="auto",
    )
    message = response.choices[0].message
    tool_calls = _extract_tool_calls(message)

    decision_messages = list(messages)
    decision_messages.append(
        {
            "role": "assistant",
            "content": message.content or "",
            **(
                {"tool_calls": [tc.model_dump() if hasattr(tc, "model_dump") else tc for tc in message.tool_calls]}
                if getattr(message, "tool_calls", None)
                else {}
            ),
        }
    )
    # Acknowledge each tool call with a placeholder result so the follow-up
    # request is valid per the chat-completions tool-calling contract; the
    # *actual* tool execution/result is owned by the workflow, not us.
    for tc in getattr(message, "tool_calls", None) or []:
        decision_messages.append(
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps({"status": "queued_for_execution_by_workflow"}),
            }
        )
    decision_messages.append(
        {
            "role": "user",
            "content": (
                "Now respond with ONLY the final structured decision "
                "(updated_memory_summary, actions_taken, next_wake_at, close_workflow)."
            ),
        }
    )

    try:
        parsed = await client.chat.completions.parse(
            model=model,
            messages=decision_messages,
            response_format=AgentDecision,
        )
        decision = parsed.choices[0].message.parsed
        assert decision is not None
    except Exception:
        decision_messages.append(
            {
                "role": "user",
                "content": (
                    "Return valid JSON only, with keys: updated_memory_summary, "
                    "actions_taken, next_wake_at, close_workflow."
                ),
            }
        )
        fallback = await client.chat.completions.create(
            model=model,
            messages=decision_messages,
            response_format={"type": "json_object"},
        )
        content = fallback.choices[0].message.content or "{}"
        decision = AgentDecision.model_validate_json(content)
    return decision, tool_calls


# --------------------------------------------------------------------- #
# Activities
# --------------------------------------------------------------------- #

@activity.defn
async def classify_event_importance(input: ClassifyInput) -> ClassifyResult:
    if _should_use_deterministic_agent(input.order_ctx.supervisor.model_config):
        important_types = {
            "customer_message",
            "customer_message_received",
            "refund_requested",
            "payment_failed",
            "shipment_delayed",
            "delivery_failed",
            "cancellation_requested",
        }
        important = input.event.type in important_types
        return ClassifyResult(
            important=important,
            reasoning=(
                "Deterministic no-key classifier woke the agent for this event."
                if important
                else "Deterministic no-key classifier logged this as routine."
            ),
        )

    client = _client_for(input.order_ctx.supervisor.model_config)
    model = _model_name(input.order_ctx.supervisor.model_config, default="gpt-4o-mini")

    messages = build_classify_messages(input)

    try:
        parsed = await client.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=ClassifyLLMOutput,
        )
        out = parsed.choices[0].message.parsed
        assert out is not None
    except Exception:
        fallback_messages = [
            *messages,
            {
                "role": "user",
                "content": "Return valid JSON only with keys: important, reasoning.",
            },
        ]
        fallback = await client.chat.completions.create(
            model=model,
            messages=fallback_messages,
            response_format={"type": "json_object"},
        )
        content = fallback.choices[0].message.content or "{}"
        out = ClassifyLLMOutput.model_validate_json(content)

    return ClassifyResult(important=out.important, reasoning=out.reasoning)


@activity.defn
async def run_agent_step(input: AgentStepInput) -> AgentStepResult:
    if _should_use_deterministic_agent(input.order_ctx.supervisor.model_config):
        tool_calls = _deterministic_tool_calls(input)
        close_workflow = "refund_requested" in set(_event_types_from_timeline(input))
        return AgentStepResult(
            updated_memory_summary=_deterministic_memory(
                input,
                "Deterministic no-key agent evaluated the latest timeline and queued appropriate mocked tools.",
            ),
            actions_taken={
                "mode": "deterministic_no_key",
                "reason": input.reason,
                "tool_calls": [tc.name for tc in tool_calls],
            },
            tool_calls=tool_calls,
            next_wake_at=None,
            close_workflow=close_workflow,
            forced=False,
        )

    client = _client_for(input.order_ctx.supervisor.model_config)
    model = _model_name(input.order_ctx.supervisor.model_config, default="gpt-4o")

    messages = build_agent_messages(input)
    decision, tool_calls = await _run_structured_agent_turn(client, model, messages)

    forced = False  # set True if a max-turns/guardrail cap forced early close upstream

    return AgentStepResult(
        updated_memory_summary=decision.updated_memory_summary,
        actions_taken=decision.actions_taken,
        tool_calls=tool_calls,
        next_wake_at=decision.next_wake_at,
        close_workflow=decision.close_workflow,
        forced=forced,
    )


@activity.defn
async def generate_final_summary(input: AgentStepInput) -> AgentStepResult:
    if _should_use_deterministic_agent(input.order_ctx.supervisor.model_config):
        return AgentStepResult(
            updated_memory_summary=_deterministic_memory(
                input,
                "Final summary: the run observed payment, shipment, customer contact, and refund-request signals; refund handling was escalated for human review.",
            ),
            actions_taken={
                "mode": "deterministic_no_key",
                "type": "final_summary",
                "recommendation": "Review refund eligibility and customer communication history.",
            },
            tool_calls=[ToolCall(name="close_workflow", args={"outcome": "deterministic_final_summary"})]
            if "close_workflow" in set(input.available_tools)
            else [],
            next_wake_at=None,
            close_workflow=True,
            forced=False,
        )

    client = _client_for(input.order_ctx.supervisor.model_config)
    model = _model_name(input.order_ctx.supervisor.model_config, default="gpt-4o")

    messages = build_final_summary_messages(input)
    decision, tool_calls = await _run_structured_agent_turn(client, model, messages)

    # Final summary pass should never leave the run open.
    return AgentStepResult(
        updated_memory_summary=decision.updated_memory_summary,
        actions_taken={**decision.actions_taken, "type": "final_summary"},
        tool_calls=[tc for tc in tool_calls if tc.name == "close_workflow"],
        next_wake_at=None,
        close_workflow=True,
        forced=False,
    )
