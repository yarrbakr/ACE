"""Transaction lifecycle endpoints — full 8-state machine via REST."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from ace.api.deps import get_identity, get_transaction_engine
from ace.api.models import (
    CreateTransactionRequest,
    DeliverResultRequest,
    DisputeRequest,
    ErrorResponse,
    SubmitQuoteRequest,
    TransactionListResponse,
    TransactionResponse,
)
from ace.core.exceptions import (
    InvalidTransitionError,
    UnauthorizedActionError,
)

if TYPE_CHECKING:
    from ace.core.identity import AgentIdentity
    from ace.core.transaction import TransactionEngine

router = APIRouter()


def _err(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "status": "error",
            "error": {"code": code, "message": message},
        },
    )


@router.post(
    "/",
    status_code=201,
    summary="Create a new transaction (buyer initiates)",
    response_model=TransactionResponse,
    responses={422: {"model": ErrorResponse}},
)
async def create_transaction(
    body: CreateTransactionRequest,
    request: Request,
    engine: TransactionEngine = Depends(get_transaction_engine),
) -> TransactionResponse | JSONResponse:
    """Buyer creates a new transaction targeting a seller's capability."""
    buyer_aid = request.state.verified_agent_id
    try:
        tx = await engine.create_transaction(
            buyer_aid=buyer_aid,
            seller_aid=body.seller_aid,
            capability_id=body.capability_id,
        )
        return TransactionResponse(transaction=tx.model_dump())
    except ValueError as exc:
        return _err("VALIDATION_ERROR", str(exc), 422)


@router.post(
    "/{tx_id}/quote",
    summary="Seller submits a price quote",
    response_model=TransactionResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def submit_quote(
    tx_id: str,
    body: SubmitQuoteRequest,
    request: Request,
    engine: TransactionEngine = Depends(get_transaction_engine),
) -> TransactionResponse | JSONResponse:
    """Seller submits a price quote for the transaction."""
    seller_aid = request.state.verified_agent_id
    try:
        tx = await engine.submit_quote(tx_id, body.price, seller_aid)
        return TransactionResponse(transaction=tx.model_dump())
    except InvalidTransitionError as exc:
        return _err("INVALID_STATE", str(exc), 409)
    except UnauthorizedActionError as exc:
        return _err("FORBIDDEN", str(exc), 403)
    except ValueError as exc:
        return _err("NOT_FOUND", str(exc), 404)


@router.post(
    "/{tx_id}/accept",
    summary="Buyer accepts the quote",
    response_model=TransactionResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def accept_quote(
    tx_id: str,
    request: Request,
    engine: TransactionEngine = Depends(get_transaction_engine),
) -> TransactionResponse | JSONResponse:
    """Buyer accepts the seller's quote and funds are escrowed."""
    buyer_aid = request.state.verified_agent_id
    try:
        tx = await engine.accept_quote(tx_id, buyer_aid)
        return TransactionResponse(transaction=tx.model_dump())
    except InvalidTransitionError as exc:
        return _err("INVALID_STATE", str(exc), 409)
    except UnauthorizedActionError as exc:
        return _err("FORBIDDEN", str(exc), 403)
    except ValueError as exc:
        return _err("NOT_FOUND", str(exc), 404)


@router.post(
    "/{tx_id}/deliver",
    summary="Seller delivers the result",
    response_model=TransactionResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def deliver_result(
    tx_id: str,
    body: DeliverResultRequest,
    request: Request,
    engine: TransactionEngine = Depends(get_transaction_engine),
) -> TransactionResponse | JSONResponse:
    """Seller delivers their result with a hash for verification."""
    seller_aid = request.state.verified_agent_id
    try:
        tx = await engine.deliver_result(tx_id, body.result_hash, seller_aid)
        return TransactionResponse(transaction=tx.model_dump())
    except InvalidTransitionError as exc:
        return _err("INVALID_STATE", str(exc), 409)
    except UnauthorizedActionError as exc:
        return _err("FORBIDDEN", str(exc), 403)
    except ValueError as exc:
        return _err("NOT_FOUND", str(exc), 404)


@router.post(
    "/{tx_id}/confirm",
    summary="Buyer confirms delivery",
    response_model=TransactionResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def confirm_delivery(
    tx_id: str,
    request: Request,
    engine: TransactionEngine = Depends(get_transaction_engine),
) -> TransactionResponse | JSONResponse:
    """Buyer confirms delivery, releasing escrow to seller."""
    buyer_aid = request.state.verified_agent_id
    try:
        tx = await engine.confirm_delivery(tx_id, buyer_aid)
        return TransactionResponse(transaction=tx.model_dump())
    except InvalidTransitionError as exc:
        return _err("INVALID_STATE", str(exc), 409)
    except UnauthorizedActionError as exc:
        return _err("FORBIDDEN", str(exc), 403)
    except ValueError as exc:
        return _err("NOT_FOUND", str(exc), 404)


@router.post(
    "/{tx_id}/dispute",
    summary="Buyer disputes the delivery",
    response_model=TransactionResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def dispute(
    tx_id: str,
    body: DisputeRequest,
    request: Request,
    engine: TransactionEngine = Depends(get_transaction_engine),
) -> TransactionResponse | JSONResponse:
    """Buyer disputes the delivery, entering the DISPUTED state."""
    buyer_aid = request.state.verified_agent_id
    try:
        tx = await engine.dispute(tx_id, buyer_aid, body.reason)
        return TransactionResponse(transaction=tx.model_dump())
    except InvalidTransitionError as exc:
        return _err("INVALID_STATE", str(exc), 409)
    except UnauthorizedActionError as exc:
        return _err("FORBIDDEN", str(exc), 403)
    except ValueError as exc:
        return _err("NOT_FOUND", str(exc), 404)


@router.get(
    "/{tx_id}",
    summary="Get transaction details",
    response_model=TransactionResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_transaction(
    tx_id: str,
    engine: TransactionEngine = Depends(get_transaction_engine),
) -> TransactionResponse | JSONResponse:
    """Retrieve a transaction's current state and history."""
    try:
        tx = await engine.get_transaction(tx_id)
        return TransactionResponse(transaction=tx.model_dump())
    except ValueError as exc:
        return _err("NOT_FOUND", str(exc), 404)


@router.get(
    "/",
    summary="List transactions",
    response_model=TransactionListResponse,
)
async def list_transactions(
    request: Request,
    role: str = Query(default="any", description="Filter by role: buyer, seller, any"),
    state: str | None = Query(default=None, description="Filter by state"),
    identity: AgentIdentity = Depends(get_identity),
    engine: TransactionEngine = Depends(get_transaction_engine),
) -> TransactionListResponse:
    """List this agent's transactions, filtered by role or state."""
    aid = identity.aid
    txs = await engine.list_transactions(aid, role=role)
    items = [tx.model_dump() for tx in txs]
    if state:
        items = [t for t in items if t.get("state") == state.upper()]
    return TransactionListResponse(transactions=items)
