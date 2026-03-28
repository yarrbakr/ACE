"""Registry API routes — FastAPI endpoints for agent discovery."""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
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

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Rate limiter (same pattern as src/ace/api/routes/gossip.py) ────

_rate_limit: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 60.0  # seconds
_RATE_LIMIT_MAX_WRITE = 10  # POST endpoints per window per IP
_RATE_LIMIT_MAX_READ = 60  # GET endpoints per window per IP


def _check_rate_limit(client_ip: str, max_requests: int) -> bool:
    """Return True if the client has exceeded the rate limit."""
    now = time.time()
    times = _rate_limit.get(client_ip, [])
    times = [t for t in times if now - t < _RATE_LIMIT_WINDOW]
    if len(times) >= max_requests:
        _rate_limit[client_ip] = times
        return True
    times.append(now)
    _rate_limit[client_ip] = times
    return False


# ── Helpers ────────────────────────────────────────────────


def _get_store(request: Request) -> RegistryStore:
    return request.app.state.store  # type: ignore[no-any-return]


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "error": {"code": code, "message": message}},
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ── Signature verification helpers ─────────────────────────


def _verify_signature(public_key_b64: str, signature_b64: str, body: bytes) -> bool:
    """Verify an Ed25519 signature against a body using a base64-encoded public key."""
    try:
        pub_bytes = base64.b64decode(public_key_b64)
        public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        sig_bytes = base64.b64decode(signature_b64)
        public_key.verify(sig_bytes, body)
        return True
    except Exception:
        return False


def _require_signature_headers(
    request: Request,
) -> tuple[str, str] | JSONResponse:
    """Extract and validate X-Agent-ID and X-Signature headers.

    Returns (agent_id, signature_b64) on success, or a JSONResponse error.
    """
    agent_id = request.headers.get("X-Agent-ID")
    signature_b64 = request.headers.get("X-Signature")
    if not agent_id:
        return _error("UNAUTHORIZED", "Missing X-Agent-ID header", 401)
    if not signature_b64:
        return _error("UNAUTHORIZED", "Missing X-Signature header", 401)
    return agent_id, signature_b64


# ── Registration ───────────────────────────────────────────


@router.post("/register", status_code=201, summary="Register an agent", response_model=None)
async def register_agent(
    body: RegisterAgentRequest, request: Request
) -> dict[str, Any] | JSONResponse:
    """Register or update an agent card in the global registry."""
    ip = _client_ip(request)
    if _check_rate_limit(ip, _RATE_LIMIT_MAX_WRITE):
        return _error("RATE_LIMITED", "Too many requests", 429)

    # Signature verification: public key comes from the agent card itself
    headers = _require_signature_headers(request)
    if isinstance(headers, JSONResponse):
        return headers
    agent_id, signature_b64 = headers

    if agent_id != body.aid:
        return _error("FORBIDDEN", "X-Agent-ID does not match request body aid", 403)

    auth = body.agent_card.get("authentication", {})
    public_key_b64 = auth.get("public_key", "")
    if not public_key_b64:
        return _error("FORBIDDEN", "agent_card missing authentication.public_key", 403)

    raw_body = await request.body()
    if not _verify_signature(public_key_b64, signature_b64, raw_body):
        return _error("FORBIDDEN", "Invalid signature", 403)

    store = _get_store(request)
    await store.register_agent(body.aid, body.agent_card)
    return {"status": "ok", "aid": body.aid, "registered": True}


@router.post("/deregister", summary="Remove an agent", response_model=None)
async def deregister_agent(
    body: DeregisterRequest, request: Request
) -> dict[str, Any] | JSONResponse:
    """Remove an agent from the registry."""
    ip = _client_ip(request)
    if _check_rate_limit(ip, _RATE_LIMIT_MAX_WRITE):
        return _error("RATE_LIMITED", "Too many requests", 429)

    headers = _require_signature_headers(request)
    if isinstance(headers, JSONResponse):
        return headers
    agent_id, signature_b64 = headers

    if agent_id != body.aid:
        return _error("FORBIDDEN", "X-Agent-ID does not match request body aid", 403)

    store = _get_store(request)
    card = await store.get_agent(body.aid)
    if card is None:
        return _error("NOT_FOUND", f"Agent not found: {body.aid}", 404)

    public_key_b64 = card.get("authentication", {}).get("public_key", "")
    if not public_key_b64:
        return _error("FORBIDDEN", "Stored agent card missing public key", 403)

    raw_body = await request.body()
    if not _verify_signature(public_key_b64, signature_b64, raw_body):
        return _error("FORBIDDEN", "Invalid signature", 403)

    await store.deregister_agent(body.aid)
    return {"status": "ok", "aid": body.aid, "deregistered": True}


# ── Heartbeat ──────────────────────────────────────────────


@router.post("/heartbeat", summary="Send a heartbeat", response_model=None)
async def heartbeat(body: HeartbeatRequest, request: Request) -> dict[str, Any] | JSONResponse:
    """Update heartbeat timestamp to keep registration alive."""
    ip = _client_ip(request)
    if _check_rate_limit(ip, _RATE_LIMIT_MAX_WRITE):
        return _error("RATE_LIMITED", "Too many requests", 429)

    headers = _require_signature_headers(request)
    if isinstance(headers, JSONResponse):
        return headers
    agent_id, signature_b64 = headers

    if agent_id != body.aid:
        return _error("FORBIDDEN", "X-Agent-ID does not match request body aid", 403)

    store = _get_store(request)
    card = await store.get_agent(body.aid)
    if card is None:
        return _error("NOT_FOUND", f"Agent not found: {body.aid}", 404)

    public_key_b64 = card.get("authentication", {}).get("public_key", "")
    if not public_key_b64:
        return _error("FORBIDDEN", "Stored agent card missing public key", 403)

    raw_body = await request.body()
    if not _verify_signature(public_key_b64, signature_b64, raw_body):
        return _error("FORBIDDEN", "Invalid signature", 403)

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
    ip = _client_ip(request)
    if _check_rate_limit(ip, _RATE_LIMIT_MAX_READ):
        return SearchResponse(status="error", results=[])

    store = _get_store(request)
    results = await store.search(q, max_price=max_price)
    return SearchResponse(results=results)


@router.get("/agents", summary="List all registered agents")
async def list_agents(request: Request) -> dict[str, Any]:
    """Return all registered agent cards."""
    ip = _client_ip(request)
    if _check_rate_limit(ip, _RATE_LIMIT_MAX_READ):
        return {"status": "error", "agents": [], "count": 0}

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
