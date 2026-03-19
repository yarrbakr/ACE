"""Comprehensive tests for the transaction state machine.

Covers: happy path, invalid transitions, authorization failures,
timeout behavior, dispute paths, escrow integration, and history audit.
"""

from __future__ import annotations

import pytest

from ace.core.exceptions import InvalidTransitionError, UnauthorizedActionError
from ace.core.transaction import (
    TransactionEngine,
    TransactionState,
    VALID_TRANSITIONS,
)
from ace.core.ledger import Ledger

CAPABILITY = "cap:test-skill-1"
THIRD_PARTY = "aid:thirdpartyzzzzz"


# ── Helpers ─────────────────────────────────────────────────


async def _run_to_executing(
    engine: TransactionEngine, buyer: str, seller: str, price: int = 500
):
    """Drive a transaction from creation through to EXECUTING state."""
    tx = await engine.create_transaction(buyer, seller, CAPABILITY)
    tx = await engine.submit_quote(tx.tx_id, price, seller)
    tx = await engine.accept_quote(tx.tx_id, buyer)
    assert tx.state == TransactionState.EXECUTING
    return tx


async def _run_to_verifying(
    engine: TransactionEngine, buyer: str, seller: str, price: int = 500
):
    """Drive a transaction from creation through to VERIFYING state."""
    tx = await _run_to_executing(engine, buyer, seller, price)
    tx = await engine.deliver_result(tx.tx_id, "sha256:abc123", seller)
    assert tx.state == TransactionState.VERIFYING
    return tx


# ── Happy path ──────────────────────────────────────────────


class TestHappyPath:
    """Test the complete INITIATED → SETTLED lifecycle."""

    async def test_full_lifecycle(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, ledger, buyer, seller = tx_setup
        price = 500

        buyer_before = await ledger.get_balance(buyer)
        seller_before = await ledger.get_balance(seller)

        tx = await engine.create_transaction(buyer, seller, CAPABILITY)
        assert tx.state == TransactionState.INITIATED
        assert tx.buyer_aid == buyer
        assert tx.seller_aid == seller

        tx = await engine.submit_quote(tx.tx_id, price, seller)
        assert tx.state == TransactionState.QUOTED
        assert tx.price == price

        tx = await engine.accept_quote(tx.tx_id, buyer)
        assert tx.state == TransactionState.EXECUTING
        assert tx.escrow_id is not None

        tx = await engine.deliver_result(tx.tx_id, "sha256:result", seller)
        assert tx.state == TransactionState.VERIFYING
        assert tx.result_hash == "sha256:result"

        tx = await engine.confirm_delivery(tx.tx_id, buyer)
        assert tx.state == TransactionState.SETTLED

        # Verify balances
        buyer_after = await ledger.get_balance(buyer)
        seller_after = await ledger.get_balance(seller)
        assert buyer_after == buyer_before - price
        assert seller_after == seller_before + price

    async def test_create_transaction_returns_valid_model(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await engine.create_transaction(buyer, seller, CAPABILITY)
        assert tx.tx_id
        assert tx.capability_id == CAPABILITY
        assert tx.price == 0
        assert tx.escrow_id is None
        assert tx.result_hash is None
        assert tx.created_at
        assert tx.timeout_at
        assert len(tx.history) == 1


# ── Invalid transitions ────────────────────────────────────


class TestInvalidTransitions:
    """Test that illegal state jumps are rejected."""

    async def test_initiated_to_settled(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await engine.create_transaction(buyer, seller, CAPABILITY)
        with pytest.raises(InvalidTransitionError):
            await engine.confirm_delivery(tx.tx_id, buyer)

    async def test_initiated_to_funded_skips_quoted(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await engine.create_transaction(buyer, seller, CAPABILITY)
        # accept_quote rejects: price is 0 (ValueError) or state wrong (InvalidTransitionError)
        with pytest.raises((InvalidTransitionError, ValueError)):
            await engine.accept_quote(tx.tx_id, buyer)

    async def test_settled_is_terminal(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_verifying(engine, buyer, seller)
        tx = await engine.confirm_delivery(tx.tx_id, buyer)
        assert tx.state == TransactionState.SETTLED

        # Cannot transition out of SETTLED
        with pytest.raises(InvalidTransitionError):
            await engine.refund(tx.tx_id)

    async def test_refunded_is_terminal(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await engine.create_transaction(buyer, seller, CAPABILITY)
        tx = await engine.refund(tx.tx_id)
        assert tx.state == TransactionState.REFUNDED

        # Cannot transition out of REFUNDED
        with pytest.raises(InvalidTransitionError):
            await engine.refund(tx.tx_id)

    async def test_executing_to_settled_invalid(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_executing(engine, buyer, seller)
        with pytest.raises(InvalidTransitionError):
            await engine.confirm_delivery(tx.tx_id, buyer)

    async def test_valid_transitions_terminal_states_empty(self):
        assert VALID_TRANSITIONS[TransactionState.SETTLED] == set()
        assert VALID_TRANSITIONS[TransactionState.REFUNDED] == set()


# ── Authorization failures ──────────────────────────────────


class TestAuthorization:
    """Test that the wrong actor is rejected for each action."""

    async def test_buyer_cannot_submit_quote(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await engine.create_transaction(buyer, seller, CAPABILITY)
        with pytest.raises(UnauthorizedActionError):
            await engine.submit_quote(tx.tx_id, 100, buyer)

    async def test_seller_cannot_accept_quote(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await engine.create_transaction(buyer, seller, CAPABILITY)
        tx = await engine.submit_quote(tx.tx_id, 100, seller)
        with pytest.raises(UnauthorizedActionError):
            await engine.accept_quote(tx.tx_id, seller)

    async def test_buyer_cannot_deliver_result(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_executing(engine, buyer, seller)
        with pytest.raises(UnauthorizedActionError):
            await engine.deliver_result(tx.tx_id, "sha256:x", buyer)

    async def test_seller_cannot_confirm_delivery(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_verifying(engine, buyer, seller)
        with pytest.raises(UnauthorizedActionError):
            await engine.confirm_delivery(tx.tx_id, seller)

    async def test_seller_cannot_dispute(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_verifying(engine, buyer, seller)
        with pytest.raises(UnauthorizedActionError):
            await engine.dispute(tx.tx_id, seller, "bad work")

    async def test_third_party_cannot_submit_quote(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await engine.create_transaction(buyer, seller, CAPABILITY)
        with pytest.raises(UnauthorizedActionError):
            await engine.submit_quote(tx.tx_id, 100, THIRD_PARTY)

    async def test_third_party_cannot_confirm_delivery(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_verifying(engine, buyer, seller)
        with pytest.raises(UnauthorizedActionError):
            await engine.confirm_delivery(tx.tx_id, THIRD_PARTY)


# ── Dispute paths ───────────────────────────────────────────


class TestDispute:
    """Test the dispute and resolution flows."""

    async def test_dispute_then_refund(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, ledger, buyer, seller = tx_setup
        price = 500
        buyer_before = await ledger.get_balance(buyer)

        tx = await _run_to_verifying(engine, buyer, seller, price)
        tx = await engine.dispute(tx.tx_id, buyer, "No good")
        assert tx.state == TransactionState.DISPUTED

        tx = await engine.resolve_dispute(tx.tx_id, buyer, "refund")
        assert tx.state == TransactionState.REFUNDED

        # Buyer gets money back
        buyer_after = await ledger.get_balance(buyer)
        assert buyer_after == buyer_before

    async def test_dispute_then_settle(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, ledger, buyer, seller = tx_setup
        price = 500
        seller_before = await ledger.get_balance(seller)

        tx = await _run_to_verifying(engine, buyer, seller, price)
        tx = await engine.dispute(tx.tx_id, buyer, "Quality concern")
        assert tx.state == TransactionState.DISPUTED

        tx = await engine.resolve_dispute(tx.tx_id, buyer, "settle")
        assert tx.state == TransactionState.SETTLED

        # Seller gets paid
        seller_after = await ledger.get_balance(seller)
        assert seller_after == seller_before + price


# ── Escrow integration ──────────────────────────────────────


class TestEscrowIntegration:
    """Test escrow state aligns with transaction state."""

    async def test_no_escrow_before_funded(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await engine.create_transaction(buyer, seller, CAPABILITY)
        assert tx.escrow_id is None

        tx = await engine.submit_quote(tx.tx_id, 100, seller)
        assert tx.escrow_id is None

    async def test_escrow_locked_after_funded(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_executing(engine, buyer, seller)
        assert tx.escrow_id is not None

        escrow = await engine._escrow.get_escrow(tx.escrow_id)
        assert escrow.state == "LOCKED"

    async def test_escrow_released_after_settled(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_verifying(engine, buyer, seller)
        tx = await engine.confirm_delivery(tx.tx_id, buyer)
        assert tx.state == TransactionState.SETTLED

        escrow = await engine._escrow.get_escrow(tx.escrow_id)
        assert escrow.state == "RELEASED"

    async def test_escrow_refunded_after_refund(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_executing(engine, buyer, seller)
        tx = await engine.refund(tx.tx_id)
        assert tx.state == TransactionState.REFUNDED

        escrow = await engine._escrow.get_escrow(tx.escrow_id)
        assert escrow.state == "REFUNDED"


# ── History audit trail ────────────────────────────────────


class TestHistory:
    """Test the immutable audit trail."""

    async def test_full_lifecycle_history(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_verifying(engine, buyer, seller)
        tx = await engine.confirm_delivery(tx.tx_id, buyer)

        # INITIATED (create) + INITIATED→QUOTED + QUOTED→FUNDED +
        # FUNDED→EXECUTING + EXECUTING→VERIFYING + VERIFYING→SETTLED = 6
        assert len(tx.history) == 6

        states = [h["to_state"] for h in tx.history]
        assert states == [
            "INITIATED", "QUOTED", "FUNDED", "EXECUTING", "VERIFYING", "SETTLED"
        ]

    async def test_every_entry_has_timestamp(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_executing(engine, buyer, seller)
        for entry in tx.history:
            assert entry["timestamp"] is not None


# ── Edge cases ──────────────────────────────────────────────


class TestEdgeCases:
    """Test validation and edge cases."""

    async def test_buyer_equals_seller_rejected(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, _ = tx_setup
        with pytest.raises(ValueError, match="different"):
            await engine.create_transaction(buyer, buyer, CAPABILITY)

    async def test_empty_capability_id_rejected(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        with pytest.raises(ValueError, match="empty"):
            await engine.create_transaction(buyer, seller, "")

    async def test_negative_price_rejected(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await engine.create_transaction(buyer, seller, CAPABILITY)
        with pytest.raises(ValueError, match="positive"):
            await engine.submit_quote(tx.tx_id, -10, seller)

    async def test_nonexistent_tx_id_raises(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, _, _ = tx_setup
        with pytest.raises(ValueError, match="not found"):
            await engine.get_transaction("nonexistent-id")

    async def test_empty_result_hash_rejected(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_executing(engine, buyer, seller)
        with pytest.raises(ValueError, match="empty"):
            await engine.deliver_result(tx.tx_id, "", seller)

    async def test_invalid_dispute_resolution(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await _run_to_verifying(engine, buyer, seller)
        tx = await engine.dispute(tx.tx_id, buyer)
        with pytest.raises(ValueError, match="'settle' or 'refund'"):
            await engine.resolve_dispute(tx.tx_id, buyer, "dismiss")


# ── List / query ────────────────────────────────────────────


class TestListTransactions:
    """Test listing and filtering transactions."""

    async def test_list_by_buyer(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        await engine.create_transaction(buyer, seller, CAPABILITY)
        txs = await engine.list_transactions(buyer, role="buyer")
        assert len(txs) == 1
        assert txs[0].buyer_aid == buyer

    async def test_list_by_seller(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        await engine.create_transaction(buyer, seller, CAPABILITY)
        txs = await engine.list_transactions(seller, role="seller")
        assert len(txs) == 1
        assert txs[0].seller_aid == seller

    async def test_list_any_role(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        await engine.create_transaction(buyer, seller, CAPABILITY)
        txs_buyer = await engine.list_transactions(buyer, role="any")
        txs_seller = await engine.list_transactions(seller, role="any")
        assert len(txs_buyer) == 1
        assert len(txs_seller) == 1

    async def test_list_empty(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, _ = tx_setup
        txs = await engine.list_transactions(buyer)
        assert txs == []


# ── Refund from various states ──────────────────────────────


class TestRefund:
    """Test refund from different pre-terminal states."""

    async def test_refund_from_initiated(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, ledger, buyer, seller = tx_setup
        buyer_before = await ledger.get_balance(buyer)
        tx = await engine.create_transaction(buyer, seller, CAPABILITY)
        tx = await engine.refund(tx.tx_id)
        assert tx.state == TransactionState.REFUNDED
        # No escrow, so buyer balance unchanged
        assert await ledger.get_balance(buyer) == buyer_before

    async def test_refund_from_quoted(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, _, buyer, seller = tx_setup
        tx = await engine.create_transaction(buyer, seller, CAPABILITY)
        tx = await engine.submit_quote(tx.tx_id, 200, seller)
        tx = await engine.refund(tx.tx_id)
        assert tx.state == TransactionState.REFUNDED

    async def test_refund_from_executing_restores_balance(
        self, tx_setup: tuple[TransactionEngine, Ledger, str, str]
    ):
        engine, ledger, buyer, seller = tx_setup
        price = 500
        buyer_before = await ledger.get_balance(buyer)

        tx = await _run_to_executing(engine, buyer, seller, price)
        tx = await engine.refund(tx.tx_id)
        assert tx.state == TransactionState.REFUNDED

        buyer_after = await ledger.get_balance(buyer)
        assert buyer_after == buyer_before
