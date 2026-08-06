"""
main.py

FastAPI application entrypoint: wires up routers, CORS, and the
startup/shutdown lifecycle for the Temporal client and DB engine.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers.runs import router as runs_router
from api.routers.supervisors import router as supervisors_router
from client import close_temporal_client, get_temporal_client
from config import settings
from db.session import dispose_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def _cors_allow_credentials() -> bool:
    if "*" in settings.cors_allow_origins:
        logger.warning(
            "CORS_ALLOW_ORIGINS contains '*'; disabling credentialed CORS "
            "because browsers reject wildcard origins with credentials."
        )
        return False
    return True


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Startup: eagerly establish the Temporal client connection so the first
    incoming request doesn't pay the connection-latency cost, and so we
    fail fast (crash on boot) if Temporal is unreachable rather than
    surfacing that as a 502 on a random request later.

    Shutdown: drop the cached Temporal client reference and dispose of the
    SQLAlchemy engine's connection pool.
    """
    logger.info("Starting up: connecting to Temporal...")
    await get_temporal_client()
    logger.info("Startup complete.")

    yield

    logger.info("Shutting down: closing Temporal client and DB engine...")
    await close_temporal_client()
    await dispose_engine()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Order Supervisor API",
    description="API for creating and managing OrderSupervisorWorkflow runs.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=_cors_allow_credentials(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs_router)
app.include_router(supervisors_router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness/readiness probe endpoint."""
    return {"status": "ok"}
