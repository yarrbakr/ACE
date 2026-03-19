"""FastAPI application factory for the ACE API server."""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ace import __version__
from ace.api.middleware import add_signature_middleware
from ace.api.routes import admin, agent, discovery, transactions
from ace.core.capability import CapabilityRegistry
from ace.core.config import AceSettings, DiscoveryMode
from ace.core.escrow import EscrowManager
from ace.core.ledger import Ledger
from ace.core.transaction import TimeoutMonitor, TransactionEngine

if TYPE_CHECKING:
    from ace.core.identity import AgentIdentity

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize shared resources on startup, tear down on shutdown."""
    settings: AceSettings = app.state.settings
    identity: AgentIdentity | None = getattr(app.state, "identity", None)

    db_path = settings.data_dir / "ace.db"
    app.state.db_path = db_path

    # Ledger
    ledger = Ledger(db_path)
    await ledger.initialize()
    app.state.ledger = ledger

    # Create agent account if identity is loaded
    if identity is not None:
        with contextlib.suppress(Exception):
            await ledger.create_account(identity.aid)

    # Escrow
    escrow_manager = EscrowManager(ledger)
    app.state.escrow_manager = escrow_manager

    # Transaction engine
    engine = TransactionEngine(ledger, escrow_manager)
    app.state.transaction_engine = engine

    # Capability registry
    registry = CapabilityRegistry(db_path)
    await registry.initialize()
    app.state.capability_registry = registry

    # Timeout monitor
    monitor = TimeoutMonitor(engine, interval=30.0)
    await monitor.start()

    # Discovery adapter
    gossip_discovery = None
    registry_discovery = None
    if settings.discovery_mode == DiscoveryMode.GOSSIP and identity is not None:
        from ace.discovery.gossip import GossipDiscovery

        gossip_discovery = GossipDiscovery(identity, settings)
        await gossip_discovery.start()
        app.state.gossip_discovery = gossip_discovery
        app.state.discovery = gossip_discovery
    elif settings.discovery_mode == DiscoveryMode.REGISTRY and identity is not None:
        from ace.discovery.public_registry import PublicRegistryDiscovery

        registry_discovery = PublicRegistryDiscovery(
            settings.registry_url,
            heartbeat_interval=settings.heartbeat_interval,
        )
        app.state.registry_discovery = registry_discovery
        app.state.discovery = registry_discovery

        # Auto-register with the public registry
        skills = await registry.list_skills()
        card = {
            "name": settings.agent_name,
            "description": settings.agent_description,
            "url": f"http://127.0.0.1:{settings.port}",
            "capabilities": [
                {
                    "id": s["name"],
                    "name": s["name"].replace("_", " ").replace("-", " ").title(),
                    "description": s.get("description", ""),
                    "pricing": {
                        "currency": s.get("currency", "AGC"),
                        "model": s.get("pricing_model", "per_call"),
                        "amount": s.get("price", 0),
                    },
                    "tags": s.get("tags", []),
                }
                for s in skills
            ],
            "authentication": {
                "type": "ed25519",
                "public_key": identity.public_key_b64,
            },
            "aid": identity.aid,
        }
        try:
            await registry_discovery.register(card)
            logger.info("Registered with public registry at %s", settings.registry_url)
        except Exception:
            logger.warning(
                "Failed to register with public registry at %s (is it running?)",
                settings.registry_url,
                exc_info=True,
            )
    else:
        from ace.discovery.centralized import CentralizedDiscovery

        centralized = CentralizedDiscovery(settings.registry_url, db_path)
        await centralized._ensure_initialized()
        app.state.discovery = centralized

    # Startup timestamp
    app.state.started_at = time.time()

    logger.info("ACE server started (v%s)", __version__)
    yield

    # Shutdown
    if registry_discovery is not None:
        if identity is not None:
            try:
                await registry_discovery.deregister(identity.aid)
            except Exception:
                logger.debug("Deregister on shutdown failed", exc_info=True)
        await registry_discovery.stop()
    if gossip_discovery is not None:
        await gossip_discovery.stop()
    await monitor.stop()
    logger.info("ACE server stopped")


def create_app(
    settings: AceSettings | None = None,
    identity: AgentIdentity | None = None,
) -> FastAPI:
    """Build and return the configured FastAPI application."""
    from ace.core.config import load_settings

    if settings is None:
        settings = load_settings()

    app = FastAPI(
        title="Agent Capability Exchange",
        description=(
            "REST API for the ACE agent marketplace — trade AI capabilities using AGC tokens."
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Store config and identity on state before lifespan runs
    app.state.settings = settings
    if identity is not None:
        app.state.identity = identity

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:*", "http://127.0.0.1:*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Signature verification
    add_signature_middleware(app)

    # Routes
    app.include_router(agent.router, prefix="/agents", tags=["agents"])
    app.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
    app.include_router(discovery.router, prefix="/discovery", tags=["discovery"])
    app.include_router(admin.router, prefix="/admin", tags=["admin"])

    # Gossip routes (only in gossip mode)
    if settings.discovery_mode == DiscoveryMode.GOSSIP:
        from ace.api.routes import gossip as gossip_routes

        app.include_router(gossip_routes.router, prefix="/gossip", tags=["gossip"])

    # ── Root-level routes ───────────────────────────────────

    @app.get("/health", tags=["system"], summary="Health check")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get(
        "/.well-known/agent.json",
        tags=["agents"],
        summary="Agent Card (A2A discovery)",
    )
    async def agent_card() -> dict[str, Any]:
        _identity: AgentIdentity | None = getattr(app.state, "identity", None)
        _settings: AceSettings = app.state.settings
        _registry: CapabilityRegistry = app.state.capability_registry

        skills = await _registry.list_skills()
        capabilities = [
            {
                "id": s["name"],
                "name": s["name"].replace("_", " ").replace("-", " ").title(),
                "description": s.get("description", ""),
                "pricing": {
                    "currency": s.get("currency", "AGC"),
                    "model": s.get("pricing_model", "per_call"),
                    "amount": s.get("price", 0),
                },
                "tags": s.get("tags", []),
                "version": s.get("version", "1.0.0"),
            }
            for s in skills
        ]

        aid = _identity.aid if _identity else _settings.aid
        public_key = _identity.public_key_b64 if _identity else ""
        url = f"http://127.0.0.1:{_settings.port}"

        return {
            "name": _settings.agent_name,
            "description": _settings.agent_description,
            "url": url,
            "capabilities": capabilities,
            "authentication": {
                "type": "ed25519",
                "public_key": public_key,
            },
            "aid": aid,
        }

    return app
