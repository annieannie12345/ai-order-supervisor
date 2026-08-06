# schemas/action.py
"""
Pydantic v2 DTOs for action/timeline read models (see
BACKEND_STRUCTURE.md §5, §8). Mirrors db.models.Action and
shared.dataclasses.TimelineEntry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ActionRead(BaseModel):
    """Response model mirroring db.models.Action."""

    id: int
    ts: datetime
    type: str  # tool_call | tool_failed | memory_updated | wake_scheduled | final_summary
    payload: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class TimelineEntryRead(BaseModel):
    """
    Response model for GET /runs/{run_id}/timeline — a UNION ALL of events
    and actions ordered by ts. Mirrors shared.dataclasses.TimelineEntry.
    """

    ts: datetime
    kind: str  # "event:*" | "agent_action" | "tool:*" | "tool_failed"
    payload: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)
