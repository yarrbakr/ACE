"""Gossip protocol HTTP endpoints — peer-to-peer communication."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ace.discovery.gossip_models import AnnounceRequest, GossipMessage, LeaveRequest

logger = logging.getLogger(__name__)

router = APIRouter()

# Simple rate-limiter: track last request time per peer AID
_rate_limit: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 60.0  # seconds
_RATE_LIMIT_MAX = 10  # max requests per window


def _check_rate_limit(aid: str) -> bool:
    """Return True if the peer has exceeded the rate limit."""
    now = time.time()
    times = _rate_limit.get(aid, [])
    # Prune old entries
    times = [t for t in times if now - t < _RATE_LIMIT_WINDOW]
    if len(times) >= _RATE_LIMIT_MAX:
        _rate_limit[aid] = times
        return True
    times.append(now)
    _rate_limit[aid] = times
    return False


def _get_gossip(request: Request) -> Any:
    """Get the GossipDiscovery instance from app state."""
    return request.app.state.gossip_discovery


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "error": {"code": code, "message": message}},
    )


@router.post("/exchange", summary="Exchange peer lists with another node", response_model=None)
async def gossip_exchange(
    message: GossipMessage, request: Request
) -> dict[str, Any] | JSONResponse:
    """Receive a peer's gossip message, merge, and return our own."""
    gossip = _get_gossip(request)

    # Rate limit
    if _check_rate_limit(message.sender_aid):
        return _error("RATE_LIMITED", "Too many gossip requests", 429)

    # Verify signature
    if not gossip._verify_message(message):
        return _error("UNAUTHORIZED", "Invalid gossip message signature", 401)

    # Merge their peers
    gossip.peer_manager.merge_peer_list(message.peers)

    # Build our response
    my_peers = gossip.peer_manager.get_all_peers()
    payload = {
        "sender_aid": gossip._identity.aid,
        "peers": [p.model_dump(mode="json") for p in my_peers],
        "timestamp": message.timestamp.isoformat(),
    }
    sig = gossip._sign_payload(payload)
    response = GossipMessage(
        sender_aid=gossip._identity.aid,
        peers=my_peers,
        signature=sig,
    )
    return response.model_dump(mode="json")


@router.get("/peers", summary="Get current peer list (for bootstrapping)")
async def gossip_peers(request: Request) -> dict[str, Any]:
    """Return our known peer list for seed-peer bootstrapping."""
    gossip = _get_gossip(request)
    peers = gossip.peer_manager.get_all_peers()
    return {"peers": [p.model_dump(mode="json") for p in peers]}


@router.post("/announce", summary="Announce a new peer to this node", response_model=None)
async def gossip_announce(
    body: AnnounceRequest, request: Request
) -> dict[str, Any] | JSONResponse:
    """Accept a peer self-announcement."""
    gossip = _get_gossip(request)
    peer = body.peer

    # Anti-spoofing: verify the announcement is signed by the peer's own key
    if not gossip.verify_peer_signature(peer, body.signature):
        return _error("FORBIDDEN", "Invalid announcement signature (spoofing?)", 403)

    gossip.peer_manager.add_peer(peer)
    return {"status": "ok", "peer_count": gossip.peer_manager.peer_count}


@router.post("/leave", summary="Graceful peer departure", response_model=None)
async def gossip_leave(body: LeaveRequest, request: Request) -> dict[str, Any] | JSONResponse:
    """Process a peer's departure notice."""
    gossip = _get_gossip(request)

    # Verify the leave is signed by the departing AID
    if not gossip.verify_aid_signature(body.aid, {"aid": body.aid}, body.signature):
        return _error("FORBIDDEN", "Invalid leave signature", 403)

    gossip.peer_manager.remove_peer(body.aid)
    return {"status": "ok"}
