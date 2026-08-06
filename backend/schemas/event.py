# schemas/event.py
"""
Pydantic v2 DTOs for inbound order events (see BACKEND_STRUCTURE.md §5, §8).
Mirrors shared.dataclasses.OrderEvent (submit_event signal payload) and
db.models.Event (Postgres read-model row).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class EventSubmit(BaseModel):
    """Payload for POST /runs/{run_id}/events; signals submit_event."""

    type: str
    payload: dict[str, Any]


class EventRead(BaseModel):
    """Response model mirroring db.models.Event."""

    id: int
    ts: datetime
    type: str
    payload: dict[str, Any]
    important: bool | None = None

    model_config = ConfigDict(from_attributes=True)
