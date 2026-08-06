# schemas/agent_step.py
"""
Pydantic v2 DTOs mirroring the LLM structured output for an agent step
(see BACKEND_STRUCTURE.md §5, §7). Mirrors shared.dataclasses.ToolCall and
shared.dataclasses.AgentStepResult, and is used as the structured-output
contract for run_agent_step / generate_final_summary activities.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolCallSchema(BaseModel):
    """Mirrors shared.dataclasses.ToolCall."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class AgentStepOutput(BaseModel):
    """
    Structured output the LLM must produce for a single agent step;
    also doubles as the API-facing mirror of
    shared.dataclasses.AgentStepResult (minus `actions_taken`, which is
    derived server-side from `tool_calls` execution results).
    """

    tool_calls: list[ToolCallSchema] = Field(default_factory=list)
    updated_memory_summary: str
    next_wake_at: datetime | None = None
    close_workflow: bool = False
    forced: bool = False

    model_config = ConfigDict(from_attributes=True)
