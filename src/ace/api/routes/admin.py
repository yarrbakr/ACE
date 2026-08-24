"""Admin endpoints — local-only balance, history, and status."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ace.api.deps import get_identity, get_ledger, get_settings, get_transaction_engine
from ace.api.models import (
    BalanceResponse,
    ErrorResponse,
    HistoryEntry,
    HistoryResponse,
    IOUDebtEntry,
    IOUDebtsResponse,
    StatusResponse,
)

if TYPE_CHECKING:
    from ace.core.config import AceSettings
    from ace.core.identity import AgentIdentity
    from ace.core.ledger import Ledger
    from ace.core.transaction import TransactionEngine

router = APIRouter()


def _localhost_guard(request: Request) -> JSONResponse | None:
    """Return an error response if the request is not from localhost."""
    host = request.client.host if request.client else None
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        return JSONResponse(
            status_code=403,
            content={
                "status": "error",
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Admin endpoints are only accessible from localhost",
                },
            },
        )
    return None


@router.get(
    "/balance",
    summary="Get the local agent's token balance",
    response_model=BalanceResponse,
    responses={403: {"model": ErrorResponse}},
)
async def get_balance(
    request: Request,
    identity: AgentIdentity = Depends(get_identity),
    ledger: Ledger = Depends(get_ledger),
) -> BalanceResponse | JSONResponse:
    """Return the current AGC token balance for this agent."""
    guard = _localhost_guard(request)
    if guard:
        return guard

    balance = await ledger.get_balance(identity.aid)
    return BalanceResponse(aid=identity.aid, balance=balance)


@router.get(
    "/history",
    summary="Get the local agent's ledger history",
    response_model=HistoryResponse,
    responses={403: {"model": ErrorResponse}},
)
async def get_history(
    request: Request,
    limit: int = 50,
    identity: AgentIdentity = Depends(get_identity),
    ledger: Ledger = Depends(get_ledger),
) -> HistoryResponse | JSONResponse:
    """Return recent ledger entries for this agent."""
    guard = _localhost_guard(request)
    if guard:
        return guard

    raw_entries = await ledger.get_transaction_history(identity.aid, limit=limit)
    entries = [
        HistoryEntry(
            entry_id=e.entry_id,
            transaction_id=e.transaction_id,
            timestamp=e.timestamp,
            direction=e.direction,
            amount=e.amount,
            balance_after=e.balance_after,
            entry_type=e.entry_type,
            description=e.description,
        )
        for e in raw_entries
    ]
    return HistoryResponse(aid=identity.aid, entries=entries)


@router.get(
    "/status",
    summary="Get agent node status and health",
    response_model=StatusResponse,
    responses={403: {"model": ErrorResponse}},
)
async def get_status(
    request: Request,
    identity: AgentIdentity = Depends(get_identity),
    settings: AceSettings = Depends(get_settings),
    engine: TransactionEngine = Depends(get_transaction_engine),
) -> StatusResponse | JSONResponse:
    """Return uptime, skill count, and active transaction count."""
    guard = _localhost_guard(request)
    if guard:
        return guard

    started_at: float = getattr(request.app.state, "started_at", time.time())
    uptime = time.time() - started_at

    registry = request.app.state.capability_registry
    skills = await registry.list_skills()
    skills_count = len(skills)

    # Count active (non-terminal) transactions
    all_txs = await engine.list_transactions(identity.aid, role="any")
    active = sum(1 for tx in all_txs if tx.state not in ("SETTLED", "REFUNDED", "DISPUTED"))

    # Gossip info
    discovery_mode = settings.discovery_mode.value
    known_peers = 0
    gossip_discovery = getattr(request.app.state, "gossip_discovery", None)
    if gossip_discovery is not None:
        known_peers = gossip_discovery.peer_manager.peer_count

    return StatusResponse(
        aid=identity.aid,
        agent_name=settings.agent_name,
        port=settings.port,
        uptime_seconds=round(uptime, 2),
        skills_count=skills_count,
        active_transactions=active,
        discovery_mode=discovery_mode,
        known_peers=known_peers,
        seed_peers=settings.seed_peers,
    )


@router.get(
    "/debts",
    summary="Get IOU debts for this agent",
    response_model=IOUDebtsResponse,
    responses={403: {"model": ErrorResponse}},
)
async def get_debts(
    request: Request,
    identity: AgentIdentity = Depends(get_identity),
    ledger: Ledger = Depends(get_ledger),
) -> IOUDebtsResponse | JSONResponse:
    """Return all pending IOU debts (as creditor or debtor) for this agent."""
    guard = _localhost_guard(request)
    if guard:
        return guard

    debts = await ledger.get_iou_debts(identity.aid)
    entries = [
        IOUDebtEntry(
            debt_id=d.debt_id,
            creditor_aid=d.creditor_aid,
            debtor_aid=d.debtor_aid,
            amount=d.amount,
            tx_id=d.tx_id,
            receipt_hash=d.receipt_hash,
            status=d.status,
            created_at=d.created_at,
        )
        for d in debts
    ]
    return IOUDebtsResponse(aid=identity.aid, debts=entries)
