"""
Shared, deterministic, serializable dataclasses used across the workflow,
activities, and API layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SupervisorConfig:
    id: str
    name: str
    base_instruction: str
    tools: list[str]
    wake_policy: dict[str, Any]
    model_config: dict[str, Any]


@dataclass
class OrderContext:
    order_id: str
    supervisor: SupervisorConfig
    order_payload: dict[str, Any]


@dataclass
class SupervisorInput:
    order_ctx: OrderContext
    initial_memory: str | None
    initial_status: str = "active"
    initial_timeline: list["TimelineEntry"] = field(default_factory=list)
    initial_extra_instructions: list[str] = field(default_factory=list)
    initial_next_wake_at: datetime | None = None


@dataclass
class OrderEvent:
    type: str
    payload: dict[str, Any]


@dataclass
class TimelineEntry:
    ts: datetime
    kind: str  # "event:*" | "agent_action" | "tool:*" | "tool_failed"
    payload: dict[str, Any]


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class AgentStepInput:
    order_ctx: OrderContext
    reason: str  # "workflow_start" | "scheduled_wakeup" | "signal" | "final_summary"
    memory_summary: str
    recent_timeline: list[TimelineEntry]
    extra_instructions: list[str]
    available_tools: list[str]


@dataclass
class AgentStepResult:
    updated_memory_summary: str
    actions_taken: dict[str, Any]
    tool_calls: list[ToolCall]
    next_wake_at: datetime | None
    close_workflow: bool
    forced: bool


@dataclass
class ClassifyInput:
    order_ctx: OrderContext
    event: OrderEvent
    memory_summary: str


@dataclass
class ClassifyResult:
    important: bool
    reasoning: str | None


@dataclass
class RunState:
    run_id: str
    status: str  # active | paused | terminated | done
    next_wake_at: datetime | None
    memory_summary: str
