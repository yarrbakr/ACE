"""Escrow module — lock, release, and refund flows for capability trades."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import aiosqlite

from ace.core.exceptions import InvalidEscrowStateError
from ace.core.ledger import SYSTEM_ESCROW, Ledger

MAX_TIMEOUT_SECONDS = 604_800  # 7 days


@dataclass(frozen=True)
class Escrow:
    """Immutable snapshot of an escrow record."""

    escrow_id: str
    buyer_aid: str
    seller_aid: str
    amount: int
    state: str
    created_at: str
    timeout_at: str
    released_at: str | None


class EscrowManager:
    """Manages escrow locks for in-flight capability transactions.

    Depends on Ledger via constructor injection for all fund movements.
    State transitions are atomic: only LOCKED -> RELEASED and
    LOCKED -> REFUNDED are valid.
    """

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger
        self._db_path = ledger._db_path  # noqa: SLF001

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            db.row_factory = aiosqlite.Row
            yield db

    async def create_escrow(
        self,
        buyer_aid: str,
        seller_aid: str,
        amount: int,
        timeout_seconds: int = 3600,
    ) -> str:
        """Lock funds from buyer into SYSTEM:ESCROW and create an escrow record.

        Returns the escrow_id (UUID4 string).
        """
        if buyer_aid == seller_aid:
            raise ValueError("Buyer and seller must be different accounts")
        if amount <= 0:
            raise ValueError("Escrow amount must be positive")
        if timeout_seconds <= 0 or timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError(f"Timeout must be between 1 and {MAX_TIMEOUT_SECONDS} seconds")

        # Lock funds via ledger
        await self._ledger.transfer(
            buyer_aid,
            SYSTEM_ESCROW,
            amount,
            description=f"Escrow lock: {amount} AGC",
            entry_type="ESCROW_LOCK",
        )

        # Insert escrow record
        escrow_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        timeout_at = (now + timedelta(seconds=timeout_seconds)).strftime("%Y-%m-%d %H:%M:%S")

        async with self._connect() as db:
            await db.execute(
                """INSERT INTO escrows
                   (escrow_id, buyer_aid, seller_aid, amount, state, timeout_at)
                   VALUES (?, ?, ?, ?, 'LOCKED', ?)""",
                (escrow_id, buyer_aid, seller_aid, amount, timeout_at),
            )
            await db.commit()

        return escrow_id

    async def release_escrow(self, escrow_id: str) -> None:
        """Release escrowed funds to the seller. LOCKED -> RELEASED."""
        seller_aid, amount = await self._transition(escrow_id, "RELEASED")
        await self._ledger.transfer(
            SYSTEM_ESCROW,
            seller_aid,
            amount,
            description=f"Escrow release: {amount} AGC",
            entry_type="ESCROW_RELEASE",
        )

    async def refund_escrow(self, escrow_id: str) -> None:
        """Refund escrowed funds back to the buyer. LOCKED -> REFUNDED."""
        buyer_aid, amount = await self._transition(escrow_id, "REFUNDED")
        await self._ledger.transfer(
            SYSTEM_ESCROW,
            buyer_aid,
            amount,
            description=f"Escrow refund: {amount} AGC",
            entry_type="ESCROW_REFUND",
        )

    async def get_escrow(self, escrow_id: str) -> Escrow:
        """Retrieve an escrow record by ID."""
        async with self._connect() as db:
            cursor = await db.execute(
                """SELECT escrow_id, buyer_aid, seller_aid, amount,
                          state, created_at, timeout_at, released_at
                   FROM escrows WHERE escrow_id = ?""",
                (escrow_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"Escrow not found: {escrow_id}")
        return Escrow(
            escrow_id=row["escrow_id"],
            buyer_aid=row["buyer_aid"],
            seller_aid=row["seller_aid"],
            amount=row["amount"],
            state=row["state"],
            created_at=row["created_at"],
            timeout_at=row["timeout_at"],
            released_at=row["released_at"],
        )

    async def check_expired_escrows(self) -> list[str]:
        """Return escrow IDs that are LOCKED and past their timeout."""
        async with self._connect() as db:
            cursor = await db.execute(
                """SELECT escrow_id FROM escrows
                   WHERE state = 'LOCKED' AND timeout_at < datetime('now')""",
            )
            rows = await cursor.fetchall()
        return [row["escrow_id"] for row in rows]

    # ── Private helpers ─────────────────────────────────────────

    async def _transition(self, escrow_id: str, target_state: str) -> tuple[str, int]:
        """Atomically move an escrow from LOCKED to *target_state*.

        Returns (recipient_aid, amount) — the seller for RELEASED,
        the buyer for REFUNDED.

        Uses UPDATE … WHERE state = 'LOCKED' so only one concurrent
        caller can succeed (prevents double-release / double-refund).
        """
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT buyer_aid, seller_aid, amount FROM escrows WHERE escrow_id = ?",
                    (escrow_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise ValueError(f"Escrow not found: {escrow_id}")

                released_clause = (
                    ", released_at = datetime('now')" if target_state == "RELEASED" else ""
                )
                cursor = await db.execute(
                    f"UPDATE escrows SET state = ?{released_clause} "  # noqa: S608
                    "WHERE escrow_id = ? AND state = 'LOCKED'",
                    (target_state, escrow_id),
                )
                if cursor.rowcount != 1:
                    raise InvalidEscrowStateError(f"Escrow {escrow_id} is not in LOCKED state")

                await db.commit()
            except Exception:
                await db.rollback()
                raise

        recipient_aid = row["seller_aid"] if target_state == "RELEASED" else row["buyer_aid"]
        return recipient_aid, row["amount"]


__all__ = [
    "Escrow",
    "EscrowManager",
]
