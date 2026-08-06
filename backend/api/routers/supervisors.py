"""
api/routers/supervisors.py

CRUD endpoints for `Supervisor` configs (see BACKEND_STRUCTURE.md §5, §8).

    POST   /supervisors        create a new supervisor
    GET    /supervisors        list supervisors
    GET    /supervisors/{id}   fetch one supervisor by id
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_session
from db.models import Supervisor
from schemas.supervisor import SupervisorCreate, SupervisorRead

router = APIRouter(prefix="/supervisors", tags=["supervisors"])


@router.post(
    "",
    response_model=SupervisorRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_supervisor(
    body: SupervisorCreate,
    session: AsyncSession = Depends(get_session),
) -> Supervisor:
    """Create a new supervisor config."""
    supervisor = Supervisor(
        name=body.name,
        base_instruction=body.base_instruction,
        tools=body.tools,
        wake_policy=body.wake_policy,
        model_config_=body.llm_config,
    )
    session.add(supervisor)
    await session.flush()
    await session.refresh(supervisor)
    return supervisor


@router.get(
    "",
    response_model=list[SupervisorRead],
)
async def list_supervisors(
    session: AsyncSession = Depends(get_session),
) -> list[Supervisor]:
    """List all supervisors."""
    result = await session.execute(select(Supervisor).order_by(Supervisor.name))
    return list(result.scalars().all())


@router.get(
    "/{supervisor_id}",
    response_model=SupervisorRead,
)
async def get_supervisor(
    supervisor_id: str,
    session: AsyncSession = Depends(get_session),
) -> Supervisor:
    """Fetch a single supervisor by id."""
    supervisor = await session.get(Supervisor, supervisor_id)
    if supervisor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Supervisor {supervisor_id!r} not found",
        )
    return supervisor
