"""Registry FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from registry import __version__
from registry.store import RegistryStore

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_DB = Path("registry_data/registry.db")
DEFAULT_PRUNE_INTERVAL = 60.0  # seconds
DEFAULT_PRUNE_MAX_AGE = 300.0  # 5 minutes


class PruneTask:
    """Background task that prunes stale agents periodically.

    Follows the same pattern as ``ace.core.transaction.TimeoutMonitor``.
    """

    def __init__(
        self, store: RegistryStore, *, interval: float = 60.0, max_age: float = 300.0
    ) -> None:
        self._store = store
        self._interval = interval
        self._max_age = max_age
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval)
                pruned = await self._store.prune_stale(self._max_age)
                if pruned:
                    logger.info("Pruned %d stale agents: %s", len(pruned), pruned)
        except asyncio.CancelledError:
            return


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize store and background pruner on startup."""
    db_path: Path = getattr(app.state, "db_path", DEFAULT_REGISTRY_DB)
    prune_interval: float = getattr(
        app.state, "prune_interval", DEFAULT_PRUNE_INTERVAL
    )
    prune_max_age: float = getattr(app.state, "prune_max_age", DEFAULT_PRUNE_MAX_AGE)

    # Initialize store
    store = RegistryStore(db_path)
    await store.initialize()
    app.state.store = store
    app.state.started_at = time.time()

    # Start background pruner
    pruner = PruneTask(store, interval=prune_interval, max_age=prune_max_age)
    await pruner.start()

    logger.info("ACE Registry started (v%s)", __version__)
    yield

    # Shutdown
    await pruner.stop()
    logger.info("ACE Registry stopped")


def create_registry_app(
    *,
    db_path: Path = DEFAULT_REGISTRY_DB,
    prune_interval: float = DEFAULT_PRUNE_INTERVAL,
    prune_max_age: float = DEFAULT_PRUNE_MAX_AGE,
) -> FastAPI:
    """Build and return the configured registry FastAPI application."""
    app = FastAPI(
        title="ACE Global Registry",
        description="Public agent discovery registry for the ACE marketplace.",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Store config on state before lifespan runs
    app.state.db_path = db_path
    app.state.prune_interval = prune_interval
    app.state.prune_max_age = prune_max_age

    # CORS — public registry allows all origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    from registry.routes import router

    app.include_router(router)

    return app


__all__ = ["PruneTask", "create_registry_app"]
