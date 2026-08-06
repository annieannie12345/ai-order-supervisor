# schemas/supervisor.py
"""
Pydantic v2 DTOs for supervisor CRUD (see BACKEND_STRUCTURE.md §5, §8).

Mirrors db.models.Supervisor. `model_config_` on the ORM model (DB column
`model_config`) is exposed here as `model_config` on the schema; the
attribute name clash with Pydantic's own `model_config` class attribute is
handled via `Field(alias=...)` + `populate_by_name`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


SECRET_MODEL_CONFIG_KEYS = {
    "api_key",
    "authorization",
    "client_secret",
    "secret",
    "token",
}


def _redact_secret_config_values(config: dict[str, Any]) -> dict[str, Any]:
    return {
        key: ("********" if key.lower() in SECRET_MODEL_CONFIG_KEYS else value)
        for key, value in config.items()
    }


class SupervisorBase(BaseModel):
    name: str
    base_instruction: str
    tools: list[str] = Field(default_factory=list)
    wake_policy: dict[str, Any] = Field(default_factory=dict)
    llm_config: dict[str, Any] = Field(
        default_factory=dict,
        alias="model_config",
        description="LLM/model settings; aliased to 'model_config' on the wire "
        "to match db.models.Supervisor.model_config_.",
    )

    model_config = ConfigDict(populate_by_name=True)


class SupervisorCreate(SupervisorBase):
    """Payload for POST /supervisors."""

    pass


class SupervisorRead(SupervisorBase):
    """Response model for supervisor read endpoints."""

    id: str

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    # Fix C4: `db.models.Supervisor` stores this column on the ORM object
    # as `model_config_` (trailing underscore, to avoid clashing with
    # Pydantic's own reserved `model_config` class attribute), while this
    # schema's field is named `llm_config` (wire alias "model_config").
    # When FastAPI serializes a `Supervisor` ORM instance through this
    # schema with `from_attributes=True`, Pydantic looks for an attribute
    # matching the field's alias or name on the source object — neither
    # `model_config` nor `llm_config` exists on the ORM object, only
    # `model_config_` does — so validation raised on every response from
    # create_supervisor/list_supervisors/get_supervisor. This validator
    # runs first and copies `model_config_` across explicitly so the
    # rest of validation has something to find, regardless of Pydantic's
    # alias-vs-attribute-name lookup behavior for from_attributes mode.
    @model_validator(mode="before")
    @classmethod
    def _map_orm_model_config(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        # `data` is an arbitrary object here (e.g. a db.models.Supervisor
        # ORM instance) because from_attributes=True is set.
        if hasattr(data, "model_config_") and not hasattr(data, "llm_config"):
            mapped = {
                "id": getattr(data, "id", None),
                "name": getattr(data, "name", None),
                "base_instruction": getattr(data, "base_instruction", None),
                "tools": list(getattr(data, "tools", None) or []),
                "wake_policy": dict(getattr(data, "wake_policy", None) or {}),
                "llm_config": _redact_secret_config_values(
                    dict(getattr(data, "model_config_", None) or {})
                ),
            }
            return mapped
        return data
