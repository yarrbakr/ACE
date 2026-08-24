"""Transaction lifecycle endpoints — full 8-state machine via REST."""

from __future__ import annotations

import base64
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
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
from ace.core.protocol import (
    CapabilityRequest,
    ConfirmNotification,
    EscrowProof,
    FundNotification,
    InboxMessage,
    InboxMessageType,
    QuoteResponse,
    TransactionReceipt,
    canonical_json,
)

if TYPE_CHECKING:
    from ace.core.identity import AgentIdentity
    from ace.core.transaction import Transaction, TransactionEngine

logger = logging.getLogger(__name__)
router = APIRouter()


def _err(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "status": "error",
            "error": {"code": code, "message": message},
        },
    )


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sign_inbox_message(
    msg: InboxMessage,
    identity: AgentIdentity,
) -> tuple[bytes, dict[str, str]]:
    """Serialize an InboxMessage to canonical JSON and sign it.

    Returns (body_bytes, headers) ready for httpx.
    """
    body_bytes = canonical_json(msg.model_dump())
    sig = identity.sign(body_bytes)
    headers = {
        "Content-Type": "application/json",
        "X-Agent-ID": identity.aid,
        "X-Signature": base64.b64encode(sig).decode(),
    }
    return body_bytes, headers


# ── Cross-agent helper coroutines ───────────────────────────────────────────


async def _initiate_cross_agent_request(
    tx: Transaction,
    seller_url: str,
    identity: AgentIdentity,
    http_client: httpx.AsyncClient,
    engine: TransactionEngine,
) -> Transaction:
    """POST CapabilityRequest to seller's inbox, apply returned quote locally."""
    cap_req = CapabilityRequest(
        tx_id=tx.tx_id,
        buyer_aid=tx.buyer_aid,
        capability_id=tx.capability_id,
        buyer_url=seller_url,  # placeholder; ideally settings.public_url
    )
    msg = InboxMessage(
        message_type=InboxMessageType.CAPABILITY_REQUEST,
        payload=cap_req.model_dump(),
    )
    body_bytes, headers = _sign_inbox_message(msg, identity)

    resp = await http_client.post(
        f"{seller_url.rstrip('/')}/agents/inbox",
        content=body_bytes,
        headers=headers,
    )
    resp.raise_for_status()
    quote = QuoteResponse(**resp.json())

    # Apply the quote on the buyer's local transaction
    await engine.submit_quote(tx.tx_id, price=quote.price, seller_aid=tx.seller_aid)
    return await engine.get_transaction(tx.tx_id)


async def _send_fund_notification(
    tx: Transaction,
    identity: AgentIdentity,
    http_client: httpx.AsyncClient,
    engine: TransactionEngine,
) -> Transaction:
    """Sign EscrowProof, POST FundNotification to seller, apply delivery locally."""
    assert tx.counterparty_url is not None  # caller guarantees this  # noqa: S101
    assert tx.escrow_id is not None  # set by accept_quote  # noqa: S101

    timestamp = _now_iso()
    proof_payload = {
        "tx_id": tx.tx_id,
        "escrow_id": tx.escrow_id,
        "buyer_aid": tx.buyer_aid,
        "seller_aid": tx.seller_aid,
        "amount": tx.price,
        "timestamp": timestamp,
    }
    proof_sig = identity.sign(canonical_json(proof_payload))
    proof = EscrowProof(
        **proof_payload,
        signature=base64.b64encode(proof_sig).decode(),
    )

    notif = FundNotification(tx_id=tx.tx_id, escrow_proof=proof)
    msg = InboxMessage(
        message_type=InboxMessageType.FUND_NOTIFICATION,
        payload=notif.model_dump(),
    )
    body_bytes, headers = _sign_inbox_message(msg, identity)

    resp = await http_client.post(
        f"{tx.counterparty_url.rstrip('/')}/agents/inbox",
        content=body_bytes,
        headers=headers,
    )
    resp.raise_for_status()

    from ace.core.protocol import DeliveryResult

    delivery = DeliveryResult(**resp.json())

    # Apply the delivery to the buyer-side transaction (EXECUTING → VERIFYING)
    await engine.deliver_result(tx.tx_id, delivery.result_hash, tx.seller_aid)
    return await engine.get_transaction(tx.tx_id)


async def _send_confirm_notification(
    tx: Transaction,
    identity: AgentIdentity,
    http_client: httpx.AsyncClient,
) -> None:
    """Sign TransactionReceipt, POST ConfirmNotification to seller's inbox."""
    assert tx.counterparty_url is not None  # caller guarantees this  # noqa: S101
    assert tx.escrow_id is not None  # noqa: S101
    assert tx.result_hash is not None  # noqa: S101

    timestamp = _now_iso()
    receipt_payload = {
        "tx_id": tx.tx_id,
        "escrow_id": tx.escrow_id,
        "buyer_aid": tx.buyer_aid,
        "seller_aid": tx.seller_aid,
        "amount": tx.price,
        "result_hash": tx.result_hash,
        "timestamp": timestamp,
    }
    receipt_sig = identity.sign(canonical_json(receipt_payload))
    receipt = TransactionReceipt(
        **receipt_payload,
        signature=base64.b64encode(receipt_sig).decode(),
    )

    notif = ConfirmNotification(tx_id=tx.tx_id, receipt=receipt)
    msg = InboxMessage(
        message_type=InboxMessageType.CONFIRM_NOTIFICATION,
        payload=notif.model_dump(),
    )
    body_bytes, headers = _sign_inbox_message(msg, identity)

    resp = await http_client.post(
        f"{tx.counterparty_url.rstrip('/')}/agents/inbox",
        content=body_bytes,
        headers=headers,
    )
    resp.raise_for_status()


# ── Route handlers ──────────────────────────────────────────────────────────


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
    identity: AgentIdentity = Depends(get_identity),
) -> TransactionResponse | JSONResponse:
    """Buyer creates a new transaction targeting a seller's capability.

    If seller_url is provided, immediately sends a CapabilityRequest to the
    seller's /inbox and applies the returned quote locally. The transaction
    is returned in QUOTED state.
    """
    buyer_aid = request.state.verified_agent_id
    try:
        tx = await engine.create_transaction(
            buyer_aid=buyer_aid,
            seller_aid=body.seller_aid,
            capability_id=body.capability_id,
            seller_url=body.seller_url,
        )
    except ValueError as exc:
        return _err("VALIDATION_ERROR", str(exc), 422)

    # Cross-agent: ensure remote seller has a local placeholder account so
    # create_escrow's FK constraint (seller_aid REFERENCES accounts) passes.
    if body.seller_url:
        ledger = request.app.state.ledger
        with contextlib.suppress(Exception):
            await ledger.create_account(body.seller_aid)

    # Cross-agent: send CapabilityRequest to seller, get quote back
    if body.seller_url:
        http_client: httpx.AsyncClient = request.app.state.http_client
        try:
            tx = await _initiate_cross_agent_request(
                tx=tx,
                seller_url=body.seller_url,
                identity=identity,
                http_client=http_client,
                engine=engine,
            )
        except Exception as exc:
            logger.warning("Cross-agent CapabilityRequest failed for %s: %s", tx.tx_id, exc)
            with contextlib.suppress(Exception):
                await engine.refund(tx.tx_id)
            return _err("UPSTREAM_ERROR", f"Failed to contact seller: {exc}", 502)

    return TransactionResponse(transaction=tx.model_dump())


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
    identity: AgentIdentity = Depends(get_identity),
) -> TransactionResponse | JSONResponse:
    """Buyer accepts the seller's quote and funds are escrowed.

    For cross-agent transactions, immediately sends a FundNotification with
    EscrowProof to the seller's /inbox and applies the returned DeliveryResult
    locally. The transaction is returned in VERIFYING state.
    """
    buyer_aid = request.state.verified_agent_id
    try:
        tx = await engine.accept_quote(tx_id, buyer_aid)
    except InvalidTransitionError as exc:
        return _err("INVALID_STATE", str(exc), 409)
    except UnauthorizedActionError as exc:
        return _err("FORBIDDEN", str(exc), 403)
    except ValueError as exc:
        return _err("NOT_FOUND", str(exc), 404)

    # Cross-agent: send FundNotification to seller, get DeliveryResult back
    if tx.counterparty_url and tx.escrow_id:
        http_client: httpx.AsyncClient = request.app.state.http_client
        try:
            tx = await _send_fund_notification(
                tx=tx,
                identity=identity,
                http_client=http_client,
                engine=engine,
            )
        except Exception as exc:
            logger.warning("FundNotification failed for %s: %s", tx_id, exc)
            return _err("UPSTREAM_ERROR", f"Seller inbox unreachable: {exc}", 502)

    return TransactionResponse(transaction=tx.model_dump())


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
    identity: AgentIdentity = Depends(get_identity),
) -> TransactionResponse | JSONResponse:
    """Buyer confirms delivery, releasing escrow to seller.

    For cross-agent transactions, escrow is released to SYSTEM:IOUS locally,
    then a signed ConfirmNotification with TransactionReceipt is sent to the
    seller's /inbox so they can record the IOU and settle their mirror tx.
    """
    buyer_aid = request.state.verified_agent_id

    # Capture tx state BEFORE confirm so we have counterparty_url + result_hash
    try:
        tx_before = await engine.get_transaction(tx_id)
    except ValueError as exc:
        return _err("NOT_FOUND", str(exc), 404)

    try:
        tx = await engine.confirm_delivery(tx_id, buyer_aid)
    except InvalidTransitionError as exc:
        return _err("INVALID_STATE", str(exc), 409)
    except UnauthorizedActionError as exc:
        return _err("FORBIDDEN", str(exc), 403)
    except ValueError as exc:
        return _err("NOT_FOUND", str(exc), 404)

    # Cross-agent: send ConfirmNotification to seller
    if tx_before.counterparty_url and tx_before.escrow_id and tx_before.result_hash:
        http_client: httpx.AsyncClient = request.app.state.http_client
        try:
            await _send_confirm_notification(
                tx=tx_before,
                identity=identity,
                http_client=http_client,
            )
        except Exception as exc:
            # Local side is already SETTLED (escrow → IOUS). Log and continue.
            # The IOU can be delivered via a retry mechanism later.
            logger.warning(
                "ConfirmNotification failed for %s: %s — local side already settled",
                tx_id,
                exc,
            )

    return TransactionResponse(transaction=tx.model_dump())


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
