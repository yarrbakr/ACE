"""Inbox endpoint — receives signed cross-agent messages from remote buyer agents."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import logging
import sqlite3
from typing import TYPE_CHECKING

import aiosqlite
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ace.api.deps import get_identity, get_ledger, get_transaction_engine
from ace.core.protocol import (
    CapabilityRequest,
    ConfirmNotification,
    DeliveryResult,
    FundNotification,
    InboxMessage,
    InboxMessageType,
    QuoteResponse,
)

if TYPE_CHECKING:
    from ace.core.identity import AgentIdentity
    from ace.core.ledger import Ledger
    from ace.core.transaction import TransactionEngine

logger = logging.getLogger(__name__)
router = APIRouter()


def _err(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"status": "error", "error": {"code": code, "message": message}},
    )


async def _get_buyer_public_key(
    db_path: object, buyer_aid: str
) -> Ed25519PublicKey | None:
    """Look up buyer's Ed25519 public key from the agents table."""
    try:
        async with aiosqlite.connect(db_path) as db:  # type: ignore[arg-type]
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT public_key FROM agents WHERE aid = ?", (buyer_aid,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            raw = base64.b64decode(row["public_key"])
            return Ed25519PublicKey.from_public_bytes(raw)
    except Exception:
        logger.debug("Failed to look up public key for %s", buyer_aid)
        return None


@router.post("/inbox", summary="Receive cross-agent inbox message")
async def inbox(
    body: InboxMessage,
    request: Request,
    engine: TransactionEngine = Depends(get_transaction_engine),
    ledger: Ledger = Depends(get_ledger),
    identity: AgentIdentity = Depends(get_identity),
) -> JSONResponse:
    """Dispatch incoming signed cross-agent messages to the appropriate handler."""
    sender_aid: str = request.state.verified_agent_id

    if body.message_type == InboxMessageType.CAPABILITY_REQUEST:
        return await _handle_capability_request(
            body.payload, sender_aid, engine, identity, request
        )
    if body.message_type == InboxMessageType.FUND_NOTIFICATION:
        return await _handle_fund_notification(
            body.payload, sender_aid, engine, identity, request
        )
    if body.message_type == InboxMessageType.CONFIRM_NOTIFICATION:
        return await _handle_confirm_notification(
            body.payload, sender_aid, engine, ledger, identity, request
        )
    return _err("UNKNOWN_MESSAGE_TYPE", f"Unknown: {body.message_type}", 400)


# ── Message handlers ────────────────────────────────────────────────────────


async def _handle_capability_request(
    payload: dict,  # type: ignore[type-arg]
    buyer_aid: str,
    engine: TransactionEngine,
    identity: AgentIdentity,
    request: Request,
) -> JSONResponse:
    """Create seller-side mirror tx, look up price, return QuoteResponse."""
    try:
        req = CapabilityRequest(**payload)
    except Exception as exc:
        return _err("VALIDATION_ERROR", str(exc), 422)

    if req.buyer_aid != buyer_aid:
        return _err("FORBIDDEN", "buyer_aid mismatch with authenticated sender", 403)

    # Look up capability price from local registry by name (capability_id = skill name)
    registry = request.app.state.capability_registry
    skills = await registry.list_skills()
    matched = next((s for s in skills if s["name"] == req.capability_id), None)
    if matched is None:
        return _err("NOT_FOUND", f"Capability not found: {req.capability_id}", 404)

    price: int = matched["price"]
    capability_name: str = matched["name"]

    # Create mirror transaction (idempotent on UNIQUE constraint)
    try:
        await engine.create_mirror_transaction(
            tx_id=req.tx_id,
            buyer_aid=req.buyer_aid,
            seller_aid=identity.aid,
            capability_id=req.capability_id,
            price=price,
            buyer_url=req.buyer_url,
        )
    except sqlite3.IntegrityError:
        # Duplicate delivery — mirror already exists, return existing quote
        pass
    except Exception as exc:
        logger.exception("create_mirror_transaction failed for %s", req.tx_id)
        return _err("INTERNAL_ERROR", f"Failed to create mirror transaction: {exc}", 500)

    response = QuoteResponse(
        tx_id=req.tx_id,
        price=price,
        seller_aid=identity.aid,
        capability_name=capability_name,
    )
    return JSONResponse(status_code=200, content=response.model_dump())


async def _handle_fund_notification(
    payload: dict,  # type: ignore[type-arg]
    buyer_aid: str,
    engine: TransactionEngine,
    identity: AgentIdentity,
    request: Request,
) -> JSONResponse:
    """Verify EscrowProof, transition mirror tx to VERIFYING, return DeliveryResult."""
    try:
        notif = FundNotification(**payload)
    except Exception as exc:
        return _err("VALIDATION_ERROR", str(exc), 422)

    proof = notif.escrow_proof

    if proof.buyer_aid != buyer_aid:
        return _err("FORBIDDEN", "EscrowProof buyer_aid mismatch with sender", 403)

    # Look up buyer's public key from agents table for proof verification
    db_path = request.app.state.db_path
    buyer_pk = await _get_buyer_public_key(db_path, proof.buyer_aid)
    if buyer_pk is None:
        return _err(
            "UNAUTHORIZED",
            f"Buyer {proof.buyer_aid} not registered with this agent",
            401,
        )

    # Verify the EscrowProof signature
    try:
        sig_bytes = base64.b64decode(proof.signature)
        buyer_pk.verify(sig_bytes, proof.signable_bytes())
    except Exception:
        return _err("FORBIDDEN", "Invalid EscrowProof signature", 403)

    # Load mirror transaction
    try:
        tx = await engine.get_transaction(proof.tx_id)
    except ValueError:
        return _err("NOT_FOUND", f"Transaction {proof.tx_id} not found", 404)

    # Verify amount and seller match
    if proof.amount != tx.price:
        return _err(
            "CONFLICT",
            f"Proof amount {proof.amount} != tx price {tx.price}",
            409,
        )
    if tx.seller_aid != identity.aid:
        return _err("FORBIDDEN", "Not the seller for this transaction", 403)

    # QUOTED → FUNDED
    try:
        await engine.acknowledge_funded(proof.tx_id, identity.aid)
    except Exception as exc:
        return _err("CONFLICT", str(exc), 409)

    # Auto-deliver: FUNDED → EXECUTING → VERIFYING
    result_hash = hashlib.sha256(
        f"result:{proof.tx_id}:{identity.aid}".encode()
    ).hexdigest()

    try:
        await engine.deliver_and_verify(proof.tx_id, identity.aid, result_hash)
    except Exception as exc:
        return _err("CONFLICT", str(exc), 409)

    response = DeliveryResult(
        tx_id=proof.tx_id,
        result_hash=result_hash,
        seller_aid=identity.aid,
    )
    return JSONResponse(status_code=200, content=response.model_dump())


async def _handle_confirm_notification(
    payload: dict,  # type: ignore[type-arg]
    buyer_aid: str,
    engine: TransactionEngine,
    ledger: Ledger,
    identity: AgentIdentity,
    request: Request,
) -> JSONResponse:
    """Verify TransactionReceipt, record IOU, settle seller-side transaction."""
    try:
        notif = ConfirmNotification(**payload)
    except Exception as exc:
        return _err("VALIDATION_ERROR", str(exc), 422)

    receipt = notif.receipt

    if receipt.buyer_aid != buyer_aid:
        return _err("FORBIDDEN", "Receipt buyer_aid mismatch with sender", 403)

    # Verify TransactionReceipt signature
    db_path = request.app.state.db_path
    buyer_pk = await _get_buyer_public_key(db_path, receipt.buyer_aid)
    if buyer_pk is None:
        return _err("UNAUTHORIZED", f"Buyer {receipt.buyer_aid} not registered", 401)

    try:
        sig_bytes = base64.b64decode(receipt.signature)
        buyer_pk.verify(sig_bytes, receipt.signable_bytes())
    except Exception:
        return _err("FORBIDDEN", "Invalid TransactionReceipt signature", 403)

    # Load mirror tx and verify receipt fields
    try:
        tx = await engine.get_transaction(receipt.tx_id)
    except ValueError:
        return _err("NOT_FOUND", f"Transaction {receipt.tx_id} not found", 404)

    if receipt.amount != tx.price:
        return _err(
            "CONFLICT",
            f"Receipt amount {receipt.amount} != tx price {tx.price}",
            409,
        )
    if receipt.seller_aid != identity.aid:
        return _err("FORBIDDEN", "Receipt seller_aid mismatch", 403)
    if tx.result_hash and receipt.result_hash != tx.result_hash:
        return _err(
            "CONFLICT",
            f"Receipt result_hash mismatch: expected {tx.result_hash}",
            409,
        )

    # Compute receipt_hash for storage
    receipt_hash = hashlib.sha256(receipt.signable_bytes()).hexdigest()

    # Record IOU (idempotent via UNIQUE constraint on tx_id)
    with contextlib.suppress(sqlite3.IntegrityError):
        await ledger.record_iou(
            creditor_aid=identity.aid,
            debtor_aid=receipt.buyer_aid,
            amount=receipt.amount,
            tx_id=receipt.tx_id,
            receipt_hash=receipt_hash,
        )

    # Settle the seller-side mirror transaction
    try:
        await engine.settle_with_iou(receipt.tx_id, identity.aid)
    except Exception as exc:
        logger.warning("settle_with_iou failed for %s: %s", receipt.tx_id, exc)

    return JSONResponse(
        status_code=200,
        content={"status": "ok", "tx_id": receipt.tx_id, "iou_recorded": True},
    )
