"""Transaction module — 8-state lifecycle engine for capability trades.

Orchestrates Ledger and EscrowManager through a strict state machine
with authorization checks, timeout monitoring, and audit history.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite
from pydantic import BaseModel, Field

from ace.core.exceptions import InvalidTransitionError, UnauthorizedActionError

if TYPE_CHECKING:
    from ace.core.escrow import EscrowManager
    from ace.core.ledger import Ledger

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


# ── State enum ──────────────────────────────────────────────


class TransactionState(str, Enum):
    """Valid transaction states — str mixin for automatic JSON serialization."""

    INITIATED = "INITIATED"
    QUOTED = "QUOTED"
    FUNDED = "FUNDED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"


# ── Legal transition map (data-driven, not if/else) ─────────

VALID_TRANSITIONS: dict[TransactionState, set[TransactionState]] = {
    TransactionState.INITIATED: {TransactionState.QUOTED, TransactionState.REFUNDED},
    TransactionState.QUOTED: {
        TransactionState.FUNDED,
        TransactionState.INITIATED,
        TransactionState.REFUNDED,
    },
    TransactionState.FUNDED: {TransactionState.EXECUTING, TransactionState.REFUNDED},
    TransactionState.EXECUTING: {
        TransactionState.VERIFYING,
        TransactionState.REFUNDED,
    },
    TransactionState.VERIFYING: {
        TransactionState.SETTLED,
        TransactionState.DISPUTED,
        TransactionState.REFUNDED,
    },
    TransactionState.DISPUTED: {TransactionState.SETTLED, TransactionState.REFUNDED},
    TransactionState.SETTLED: set(),  # terminal
    TransactionState.REFUNDED: set(),  # terminal
}

# States that are "active" (have a timeout and can expire)
_ACTIVE_STATES = {
    TransactionState.INITIATED,
    TransactionState.QUOTED,
    TransactionState.FUNDED,
    TransactionState.EXECUTING,
    TransactionState.VERIFYING,
    TransactionState.DISPUTED,
}

# Default timeouts per state (seconds)
_STATE_TIMEOUTS: dict[TransactionState, int] = {
    TransactionState.INITIATED: 300,  # 5 minutes for seller to quote
    TransactionState.QUOTED: 60,  # 60 seconds for buyer to accept
    TransactionState.FUNDED: 600,  # 10 minutes for execution
    TransactionState.EXECUTING: 600,  # 10 minutes for delivery
    TransactionState.VERIFYING: 86_400,  # 24 hours for verification
    TransactionState.DISPUTED: 604_800,  # 7 days for dispute resolution
}


# ── Pydantic model ──────────────────────────────────────────


class Transaction(BaseModel):
    """Snapshot of a transaction record with its full history."""

    tx_id: str
    state: TransactionState
    buyer_aid: str
    seller_aid: str
    capability_id: str
    price: int = 0
    escrow_id: str | None = None
    result_hash: str | None = None
    created_at: str
    updated_at: str
    timeout_at: str
    history: list[dict[str, Any]] = Field(default_factory=list)


# ── Transaction engine ──────────────────────────────────────


class TransactionEngine:
    """Drives the transaction lifecycle through its 8-state machine.

    Depends on Ledger and EscrowManager via constructor injection.
    All state changes flow through _transition() — the single choke point.
    """

    def __init__(self, ledger: Ledger, escrow_manager: EscrowManager) -> None:
        self._ledger = ledger
        self._escrow = escrow_manager
        self._db_path = ledger._db_path  # noqa: SLF001

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            db.row_factory = aiosqlite.Row
            yield db

    # ── Core state transition (single choke point) ──────────

    async def _transition(
        self,
        tx_id: str,
        expected_from: TransactionState,
        to_state: TransactionState,
        actor_aid: str | None = None,
        note: str | None = None,
    ) -> None:
        """Atomically transition a transaction, validating legality.

        Raises InvalidTransitionError if the transition is not in VALID_TRANSITIONS.
        """
        if to_state not in VALID_TRANSITIONS.get(expected_from, set()):
            raise InvalidTransitionError(
                f"Cannot transition from {expected_from.value} to {to_state.value}"
            )

        timeout_at = self._compute_timeout(to_state)

        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT state FROM transactions WHERE tx_id = ?",
                    (tx_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise ValueError(f"Transaction not found: {tx_id}")

                current = TransactionState(row["state"])
                if current != expected_from:
                    raise InvalidTransitionError(
                        f"Expected state {expected_from.value}, found {current.value}"
                    )

                await db.execute(
                    "UPDATE transactions SET state = ?, updated_at = datetime('now'), "
                    "timeout_at = ? WHERE tx_id = ? AND state = ?",
                    (to_state.value, timeout_at, tx_id, expected_from.value),
                )

                await db.execute(
                    "INSERT INTO transaction_history "
                    "(tx_id, from_state, to_state, actor_aid, note) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        tx_id,
                        expected_from.value,
                        to_state.value,
                        actor_aid,
                        note,
                    ),
                )

                await db.commit()
            except Exception:
                await db.rollback()
                raise

    @staticmethod
    def _compute_timeout(state: TransactionState) -> str:
        seconds = _STATE_TIMEOUTS.get(state, 0)
        if seconds:
            dt = datetime.now(UTC) + timedelta(seconds=seconds)
        else:
            # Terminal states — set far future
            dt = datetime(9999, 12, 31, tzinfo=UTC)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    # ── Authorization helper ────────────────────────────────

    @staticmethod
    def _check_actor(actual: str, expected: str, action: str) -> None:
        if actual != expected:
            raise UnauthorizedActionError(f"{action} requires actor {expected}, got {actual}")

    # ── Public methods ──────────────────────────────────────

    async def create_transaction(
        self,
        buyer_aid: str,
        seller_aid: str,
        capability_id: str,
    ) -> Transaction:
        """Create a new transaction in INITIATED state."""
        if buyer_aid == seller_aid:
            raise ValueError("Buyer and seller must be different agents")
        if not capability_id or not capability_id.strip():
            raise ValueError("capability_id must not be empty")

        tx_id = str(uuid.uuid4())
        timeout_at = self._compute_timeout(TransactionState.INITIATED)

        async with self._connect() as db:
            await db.execute(
                "INSERT INTO transactions "
                "(tx_id, state, buyer_aid, seller_aid, capability_id, timeout_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    tx_id,
                    TransactionState.INITIATED.value,
                    buyer_aid,
                    seller_aid,
                    capability_id,
                    timeout_at,
                ),
            )
            await db.execute(
                "INSERT INTO transaction_history "
                "(tx_id, from_state, to_state, actor_aid, note) "
                "VALUES (?, NULL, ?, ?, ?)",
                (tx_id, TransactionState.INITIATED.value, buyer_aid, "Transaction created"),
            )
            await db.commit()

        return await self.get_transaction(tx_id)

    async def submit_quote(self, tx_id: str, price: int, seller_aid: str) -> Transaction:
        """Seller submits a price quote. INITIATED → QUOTED."""
        if price <= 0:
            raise ValueError("Price must be positive")

        tx = await self.get_transaction(tx_id)
        self._check_actor(seller_aid, tx.seller_aid, "submit_quote")

        await self._transition(
            tx_id,
            TransactionState.INITIATED,
            TransactionState.QUOTED,
            actor_aid=seller_aid,
            note=f"Quote: {price} AGC",
        )

        async with self._connect() as db:
            await db.execute(
                "UPDATE transactions SET price = ? WHERE tx_id = ?",
                (price, tx_id),
            )
            await db.commit()

        return await self.get_transaction(tx_id)

    async def accept_quote(self, tx_id: str, buyer_aid: str) -> Transaction:
        """Buyer accepts quote, creates escrow. QUOTED → FUNDED → EXECUTING."""
        tx = await self.get_transaction(tx_id)
        self._check_actor(buyer_aid, tx.buyer_aid, "accept_quote")

        if tx.price <= 0:
            raise ValueError("Cannot accept a quote with zero price")

        # Transition QUOTED → FUNDED
        await self._transition(
            tx_id,
            TransactionState.QUOTED,
            TransactionState.FUNDED,
            actor_aid=buyer_aid,
            note="Quote accepted, escrow created",
        )

        # Create escrow atomically
        escrow_id = await self._escrow.create_escrow(
            buyer_aid=tx.buyer_aid,
            seller_aid=tx.seller_aid,
            amount=tx.price,
            timeout_seconds=_STATE_TIMEOUTS[TransactionState.FUNDED],
        )

        async with self._connect() as db:
            await db.execute(
                "UPDATE transactions SET escrow_id = ? WHERE tx_id = ?",
                (escrow_id, tx_id),
            )
            await db.commit()

        # Auto-transition FUNDED → EXECUTING
        await self._transition(
            tx_id,
            TransactionState.FUNDED,
            TransactionState.EXECUTING,
            actor_aid=buyer_aid,
            note="Auto-transition to executing",
        )

        return await self.get_transaction(tx_id)

    async def deliver_result(self, tx_id: str, result_hash: str, seller_aid: str) -> Transaction:
        """Seller delivers the result. EXECUTING → VERIFYING."""
        if not result_hash or not result_hash.strip():
            raise ValueError("result_hash must not be empty")

        tx = await self.get_transaction(tx_id)
        self._check_actor(seller_aid, tx.seller_aid, "deliver_result")

        await self._transition(
            tx_id,
            TransactionState.EXECUTING,
            TransactionState.VERIFYING,
            actor_aid=seller_aid,
            note=f"Result delivered: {result_hash}",
        )

        async with self._connect() as db:
            await db.execute(
                "UPDATE transactions SET result_hash = ? WHERE tx_id = ?",
                (result_hash, tx_id),
            )
            await db.commit()

        return await self.get_transaction(tx_id)

    async def confirm_delivery(self, tx_id: str, buyer_aid: str) -> Transaction:
        """Buyer confirms delivery, releases escrow. VERIFYING → SETTLED."""
        tx = await self.get_transaction(tx_id)
        self._check_actor(buyer_aid, tx.buyer_aid, "confirm_delivery")

        await self._transition(
            tx_id,
            TransactionState.VERIFYING,
            TransactionState.SETTLED,
            actor_aid=buyer_aid,
            note="Delivery confirmed, escrow released",
        )

        if tx.escrow_id:
            await self._escrow.release_escrow(tx.escrow_id)

        return await self.get_transaction(tx_id)

    async def dispute(self, tx_id: str, buyer_aid: str, reason: str = "") -> Transaction:
        """Buyer disputes delivery. VERIFYING → DISPUTED."""
        tx = await self.get_transaction(tx_id)
        self._check_actor(buyer_aid, tx.buyer_aid, "dispute")

        await self._transition(
            tx_id,
            TransactionState.VERIFYING,
            TransactionState.DISPUTED,
            actor_aid=buyer_aid,
            note=f"Disputed: {reason}" if reason else "Disputed",
        )

        return await self.get_transaction(tx_id)

    async def resolve_dispute(self, tx_id: str, actor_aid: str, resolution: str) -> Transaction:
        """Resolve a dispute — settle (pay seller) or refund (return to buyer).

        resolution must be 'settle' or 'refund'.
        """
        if resolution not in ("settle", "refund"):
            raise ValueError("Resolution must be 'settle' or 'refund'")

        tx = await self.get_transaction(tx_id)

        if resolution == "settle":
            await self._transition(
                tx_id,
                TransactionState.DISPUTED,
                TransactionState.SETTLED,
                actor_aid=actor_aid,
                note="Dispute resolved: seller paid",
            )
            if tx.escrow_id:
                await self._escrow.release_escrow(tx.escrow_id)
        else:
            await self._transition(
                tx_id,
                TransactionState.DISPUTED,
                TransactionState.REFUNDED,
                actor_aid=actor_aid,
                note="Dispute resolved: buyer refunded",
            )
            if tx.escrow_id:
                await self._escrow.refund_escrow(tx.escrow_id)

        return await self.get_transaction(tx_id)

    async def refund(self, tx_id: str) -> Transaction:
        """Refund a transaction from most states. Handles escrow if it exists."""
        tx = await self.get_transaction(tx_id)

        await self._transition(
            tx_id,
            TransactionState(tx.state),
            TransactionState.REFUNDED,
            actor_aid=None,
            note="Refund",
        )

        if tx.escrow_id:
            try:
                await self._escrow.refund_escrow(tx.escrow_id)
            except Exception:
                logger.warning("Escrow refund failed for %s", tx.escrow_id)

        return await self.get_transaction(tx_id)

    # ── Query methods ───────────────────────────────────────

    async def get_transaction(self, tx_id: str) -> Transaction:
        """Load a transaction with its complete history."""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT tx_id, state, buyer_aid, seller_aid, capability_id, "
                "price, escrow_id, result_hash, created_at, updated_at, timeout_at "
                "FROM transactions WHERE tx_id = ?",
                (tx_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"Transaction not found: {tx_id}")

            cursor = await db.execute(
                "SELECT from_state, to_state, actor_aid, timestamp, note "
                "FROM transaction_history WHERE tx_id = ? ORDER BY timestamp, id",
                (tx_id,),
            )
            history_rows = await cursor.fetchall()

        history = [
            {
                "from_state": h["from_state"],
                "to_state": h["to_state"],
                "actor_aid": h["actor_aid"],
                "timestamp": h["timestamp"],
                "note": h["note"],
            }
            for h in history_rows
        ]

        return Transaction(
            tx_id=row["tx_id"],
            state=TransactionState(row["state"]),
            buyer_aid=row["buyer_aid"],
            seller_aid=row["seller_aid"],
            capability_id=row["capability_id"],
            price=row["price"],
            escrow_id=row["escrow_id"],
            result_hash=row["result_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            timeout_at=row["timeout_at"],
            history=history,
        )

    async def list_transactions(self, aid: str, role: str = "any") -> list[Transaction]:
        """List transactions for an agent, optionally filtered by role."""
        if role == "buyer":
            where = "WHERE buyer_aid = ?"
        elif role == "seller":
            where = "WHERE seller_aid = ?"
        elif role == "any":
            where = "WHERE buyer_aid = ? OR seller_aid = ?"
        else:
            raise ValueError(f"Invalid role filter: {role}")

        async with self._connect() as db:
            params: tuple[str, ...] = (aid, aid) if role == "any" else (aid,)
            cursor = await db.execute(
                "SELECT tx_id FROM transactions " + where + " ORDER BY created_at DESC",
                params,
            )
            rows = await cursor.fetchall()

        return [await self.get_transaction(row["tx_id"]) for row in rows]


# ── Timeout monitor ─────────────────────────────────────────


class TimeoutMonitor:
    """Background task that auto-refunds/disputes expired transactions.

    - FUNDED / EXECUTING past timeout → auto-refund (buyer protected)
    - VERIFYING past timeout → auto-dispute
    """

    def __init__(self, engine: TransactionEngine, interval: float = 10.0) -> None:
        self._engine = engine
        self._interval = interval
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self._check_timeouts()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("TimeoutMonitor check failed")
            await asyncio.sleep(self._interval)

    async def _check_timeouts(self) -> None:
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

        async with self._engine._connect() as db:  # noqa: SLF001
            cursor = await db.execute(
                "SELECT tx_id, state FROM transactions "
                "WHERE state IN ('FUNDED', 'EXECUTING', 'VERIFYING') "
                "AND timeout_at < ?",
                (now,),
            )
            rows = await cursor.fetchall()

        for row in rows:
            tx_id = row["tx_id"]
            state = TransactionState(row["state"])
            try:
                if state in (
                    TransactionState.FUNDED,
                    TransactionState.EXECUTING,
                ):
                    await self._engine.refund(tx_id)
                    logger.info("Timeout refund: %s", tx_id)
                elif state == TransactionState.VERIFYING:
                    tx = await self._engine.get_transaction(tx_id)
                    await self._engine.dispute(tx_id, tx.buyer_aid, reason="Verification timeout")
                    logger.info("Timeout dispute: %s", tx_id)
            except Exception:
                logger.exception("Timeout action failed for %s", tx_id)


__all__ = [
    "Transaction",
    "TransactionEngine",
    "TransactionState",
    "TimeoutMonitor",
    "VALID_TRANSITIONS",
]
