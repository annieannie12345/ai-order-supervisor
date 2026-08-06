"""
client.py

Shared Temporal client factory. Used by:
  - `main.py` / `api/deps.py` (FastAPI `get_temporal_client` dependency) to
    start workflows, send signals, and run queries from HTTP handlers.
  - `worker.py` to connect the Worker to the same Temporal server/namespace.
  - `scripts/event_generator.py` and other standalone scripts that need to
    signal a running workflow outside of a request/response cycle.

A single client instance is cached and reused (Temporal clients are cheap
to share and are explicitly designed for concurrent use), rather than
opening a new connection per call/request.
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client, TLSConfig

from config import settings

logger = logging.getLogger("client")

# --------------------------------------------------------------------------
# Cached client
# --------------------------------------------------------------------------
#
# Guarded by a lock so concurrent callers (e.g. multiple FastAPI requests
# racing on startup) don't each open a separate connection before the first
# one finishes.

_client: Client | None = None
_client_lock = asyncio.Lock()


async def get_temporal_client() -> Client:
    """
    Return a process-wide, lazily-initialized, cached `Client` connected to
    `settings.temporal_target_host` / `settings.temporal_namespace`.

    Safe to call repeatedly and concurrently — subsequent calls return the
    same connected client rather than reconnecting.
    """
    global _client

    if _client is not None:
        return _client

    async with _client_lock:
        # Re-check inside the lock: another task may have finished
        # connecting while we were waiting on it.
        if _client is not None:
            return _client

        logger.info(
            "Connecting to Temporal target=%r namespace=%r tls=%s",
            settings.temporal_target_host,
            settings.temporal_namespace,
            settings.temporal_tls_enabled,
        )

        _client = await Client.connect(
            settings.temporal_target_host,
            namespace=settings.temporal_namespace,
            tls=_build_tls_config(),
        )

    return _client


def _build_tls_config() -> TLSConfig | bool:
    """
    Returns a `TLSConfig` for Temporal Cloud-style mTLS if client cert/key
    are configured, `True` for plain TLS-without-mTLS, or `False` for local
    dev (e.g. `temporal server start-dev`) with no TLS at all.
    """
    if not settings.temporal_tls_enabled:
        return False

    if settings.temporal_tls_client_cert and settings.temporal_tls_client_key:
        return TLSConfig(
            client_cert=settings.temporal_tls_client_cert.encode(),
            client_private_key=settings.temporal_tls_client_key.encode(),
        )

    return True


async def close_temporal_client() -> None:
    """
    Drop the cached client reference. Call from FastAPI's shutdown handler
    for symmetry with startup wiring; the underlying gRPC channel is closed
    when the process exits. Safe to call even if no client was ever created.
    """
    global _client
    _client = None


# --------------------------------------------------------------------------
# FastAPI dependency
# --------------------------------------------------------------------------


async def get_temporal_client_dependency() -> Client:
    """
    FastAPI dependency wrapper, e.g.:

        @router.post("/runs")
        async def create_run(
            body: RunCreate,
            temporal_client: Client = Depends(get_temporal_client_dependency),
        ) -> RunRead:
            ...

    Thin alias over `get_temporal_client()` — kept as a separate name so
    `api/deps.py` can import a dependency-shaped function without callers
    needing to know it's just the cached-client getter under the hood.
    """
    return await get_temporal_client()
