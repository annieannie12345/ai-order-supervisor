# schemas/run.py
"""
Pydantic v2 DTOs for run creation/read and RunState (see
BACKEND_STRUCTURE.md §5, §8). Mirrors db.models.Run and
shared.dataclasses.RunState.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RunCreate(BaseModel):
    """Payload for POST /runs."""

    order_id: str
    supervisor_id: str
    order_payload: dict[str, Any]
    initial_memory: str | None = None


class RunRead(BaseModel):
    """Response model mirroring db.models.Run (Postgres read-model row)."""

    id: str
    order_id: str
    supervisor_id: str
    workflow_id: str
    status: str
    next_wake_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunStateRead(BaseModel):
    """
    Response model for GET /runs/{run_id}; mirrors the workflow's
    `get_state` query result (shared.dataclasses.RunState) when the
    workflow is open, or is assembled from the Postgres mirror otherwise.
    """

    run_id: str
    status: str  # active | paused | terminated | done
    next_wake_at: datetime | None
    memory_summary: str

    model_config = ConfigDict(from_attributes=True)
