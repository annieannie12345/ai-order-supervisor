"""
api/deps.py

FastAPI dependency wrappers around the shared DB session factory and
Temporal client, for use in router signatures via `Depends(...)`.
"""

from __future__ import annotations

from temporalio.client import Client

from client import get_temporal_client_dependency
from db.session import get_session as _get_session


# Fix C2: `db.session.get_session` is *itself* an async-generator FastAPI
# dependency (it already handles commit/rollback/close). The previous
# implementation wrapped it in `_get_session_context()` and then did
# `async with _get_session_context() as session:` — but calling an async
# generator function just returns an async generator *object*, which does
# not implement `__aenter__`/`__aexit__`. That raised
# `'async_generator' object does not support the asynchronous context
# manager protocol` on every request that depended on `get_session`
# (i.e. nearly the entire API). Simply re-export the generator directly;
# FastAPI knows how to drive a `Depends(...)`-async-generator dependency
# itself, no wrapping needed.
get_session = _get_session


async def get_temporal_client() -> Client:
    """
    FastAPI dependency returning the process-wide cached Temporal `Client`.

    Thin alias over `client.get_temporal_client_dependency()`, e.g.:

        @router.post("/runs")
        async def create_run(
            body: RunCreate,
            session: AsyncSession = Depends(get_session),
            temporal_client: Client = Depends(get_temporal_client),
        ) -> RunRead:
            ...
    """
    return await get_temporal_client_dependency()
