# schemas/instruction.py
"""
Pydantic v2 DTO for the add_instruction signal payload (see
BACKEND_STRUCTURE.md §5, §8).
"""

from __future__ import annotations

from pydantic import BaseModel


class InstructionSubmit(BaseModel):
    """Payload for POST /runs/{run_id}/instructions; signals add_instruction."""

    instruction: str
