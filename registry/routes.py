"""Registry API routes — FastAPI endpoints for agent discovery."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from registry import __version__
from registry.models import (
    DeregisterRequest,
    HeartbeatRequest,
    RegisterAgentRequest,
    RegistryStatsResponse,
    SearchResponse,
)
from registry.store import RegistryStore

router = APIRouter()


def _get_store(request: Request) -> RegistryStore:
    return request.app.state.store  # type: ignore[no-any-return]


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "error": {"code": code, "message": message}},
    )


# ── Registration ───────────────────────────────────────────


@router.post("/register", status_code=201, summary="Register an agent")
async def register_agent(
    body: RegisterAgentRequest, request: Request
) -> dict[str, Any]:
    """Register or update an agent card in the global registry."""
    store = _get_store(request)
    await store.register_agent(body.aid, body.agent_card)
    return {"status": "ok", "aid": body.aid, "registered": True}


@router.post("/deregister", summary="Remove an agent", response_model=None)
async def deregister_agent(
    body: DeregisterRequest, request: Request
) -> dict[str, Any] | JSONResponse:
    """Remove an agent from the registry."""
    store = _get_store(request)
    existed = await store.deregister_agent(body.aid)
    if not existed:
        return _error("NOT_FOUND", f"Agent not found: {body.aid}", 404)
    return {"status": "ok", "aid": body.aid, "deregistered": True}


# ── Heartbeat ──────────────────────────────────────────────


@router.post("/heartbeat", summary="Send a heartbeat", response_model=None)
async def heartbeat(
    body: HeartbeatRequest, request: Request
) -> dict[str, Any] | JSONResponse:
    """Update heartbeat timestamp to keep registration alive."""
    store = _get_store(request)
    found = await store.heartbeat(body.aid)
    if not found:
        return _error("NOT_FOUND", f"Agent not found: {body.aid}", 404)
    return {"status": "ok", "aid": body.aid}


# ── Search & Listing ───────────────────────────────────────


@router.get("/search", summary="Search for capabilities")
async def search_capabilities(
    request: Request,
    q: str = Query(description="Search query"),
    max_price: int | None = Query(default=None, description="Max price filter"),
) -> SearchResponse:
    """Search the global registry for agent capabilities."""
    store = _get_store(request)
    results = await store.search(q, max_price=max_price)
    return SearchResponse(results=results)


@router.get("/agents", summary="List all registered agents")
async def list_agents(request: Request) -> dict[str, Any]:
    """Return all registered agent cards."""
    store = _get_store(request)
    agents = await store.list_agents()
    return {"status": "ok", "agents": agents, "count": len(agents)}


@router.get("/agents/{aid}", summary="Get agent by AID", response_model=None)
async def get_agent(aid: str, request: Request) -> dict[str, Any] | JSONResponse:
    """Retrieve a specific agent's card by AID."""
    store = _get_store(request)
    card = await store.get_agent(aid)
    if card is None:
        return _error("NOT_FOUND", f"Agent not found: {aid}", 404)
    return {"status": "ok", "agent": card}


# ── Health ─────────────────────────────────────────────────


@router.get("/health", summary="Registry health check")
async def health(request: Request) -> RegistryStatsResponse:
    """Return registry health and statistics."""
    store = _get_store(request)
    started_at: float = getattr(request.app.state, "started_at", time.time())
    count = await store.agent_count()
    return RegistryStatsResponse(
        version=__version__,
        agent_count=count,
        uptime_seconds=round(time.time() - started_at, 2),
    )
