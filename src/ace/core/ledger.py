"""Ledger module — double-entry bookkeeping, transfers, and minting."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from ace.core.exceptions import AccountNotFoundError, InsufficientBalanceError

SYSTEM_ISSUANCE = "SYSTEM:ISSUANCE"
SYSTEM_ESCROW = "SYSTEM:ESCROW"
SYSTEM_BURN = "SYSTEM:BURN"
SYSTEM_FEES = "SYSTEM:FEES"

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


@dataclass(frozen=True)
class LedgerEntry:
    """A single ledger entry (one side of a double-entry transaction)."""

    entry_id: str
    transaction_id: str
    timestamp: str
    account: str
    direction: str  # 'DEBIT' or 'CREDIT'
    amount: int
    balance_after: int
    entry_type: str
    description: str


class Ledger:
    """Double-entry bookkeeping ledger for ACE token transfers.

    Every financial operation creates exactly two entries: one DEBIT
    and one CREDIT. The sum of all DEBITs always equals the sum of
    all CREDITs across the entire ledger.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """Open a connection with WAL mode and FK enforcement."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            db.row_factory = aiosqlite.Row
            yield db

    async def initialize(self) -> None:
        """Create tables from schema.sql if they don't exist."""
        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(schema_sql)

    async def create_account(self, aid: str) -> None:
        """Create a new account with zero balance.

        Raises sqlite3.IntegrityError if account already exists.
        """
        async with self._connect() as db:
            await db.execute(
                "INSERT INTO accounts (aid, balance) VALUES (?, 0)",
                (aid,),
            )
            await db.commit()

    async def get_balance(self, aid: str) -> int:
        """Return the current balance for the given account.

        Raises AccountNotFoundError if the account does not exist.
        """
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT balance FROM accounts WHERE aid = ?",
                (aid,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise AccountNotFoundError(f"Account not found: {aid}")
            return row[0]  # type: ignore[no-any-return]

    async def transfer(
        self,
        from_aid: str,
        to_aid: str,
        amount: int,
        description: str = "",
        entry_type: str | None = None,
    ) -> str:
        """Execute a double-entry transfer between two accounts.

        Returns the transaction_id (UUID4 string).

        Raises:
            ValueError: if amount <= 0 or from_aid == to_aid
            AccountNotFoundError: if either account does not exist
            InsufficientBalanceError: if sender has insufficient funds
        """
        if amount <= 0:
            raise ValueError(f"Transfer amount must be positive, got {amount}")
        if from_aid == to_aid:
            raise ValueError("Cannot transfer to the same account")

        transaction_id = str(uuid.uuid4())

        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                # Read sender balance INSIDE the transaction
                cursor = await db.execute(
                    "SELECT balance FROM accounts WHERE aid = ?", (from_aid,)
                )
                sender_row = await cursor.fetchone()
                if sender_row is None:
                    raise AccountNotFoundError(f"Account not found: {from_aid}")
                sender_balance: int = sender_row[0]

                # Read receiver balance INSIDE the transaction
                cursor = await db.execute(
                    "SELECT balance FROM accounts WHERE aid = ?", (to_aid,)
                )
                receiver_row = await cursor.fetchone()
                if receiver_row is None:
                    raise AccountNotFoundError(f"Account not found: {to_aid}")
                receiver_balance: int = receiver_row[0]

                # Check sufficient funds (system accounts can go negative)
                if not from_aid.startswith("SYSTEM:") and sender_balance < amount:
                    raise InsufficientBalanceError(
                        f"Insufficient balance: {sender_balance} < {amount}"
                    )

                new_sender_balance = sender_balance - amount
                new_receiver_balance = receiver_balance + amount

                resolved_entry_type = entry_type or (
                    "ISSUANCE" if from_aid == SYSTEM_ISSUANCE else "TRANSFER"
                )

                # DEBIT entry (sender — balance goes down)
                await db.execute(
                    """INSERT INTO ledger_entries
                       (entry_id, transaction_id, account, direction,
                        amount, balance_after, entry_type, description)
                       VALUES (?, ?, ?, 'DEBIT', ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        transaction_id,
                        from_aid,
                        amount,
                        new_sender_balance,
                        resolved_entry_type,
                        description,
                    ),
                )

                # CREDIT entry (receiver — balance goes up)
                await db.execute(
                    """INSERT INTO ledger_entries
                       (entry_id, transaction_id, account, direction,
                        amount, balance_after, entry_type, description)
                       VALUES (?, ?, ?, 'CREDIT', ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        transaction_id,
                        to_aid,
                        amount,
                        new_receiver_balance,
                        resolved_entry_type,
                        description,
                    ),
                )

                # Update both account balances atomically
                await db.execute(
                    "UPDATE accounts SET balance = ?, updated_at = datetime('now') WHERE aid = ?",
                    (new_sender_balance, from_aid),
                )
                await db.execute(
                    "UPDATE accounts SET balance = ?, updated_at = datetime('now') WHERE aid = ?",
                    (new_receiver_balance, to_aid),
                )

                await db.commit()
            except Exception:
                await db.rollback()
                raise

        return transaction_id

    async def mint(
        self,
        to_aid: str,
        amount: int,
        description: str = "",
    ) -> str:
        """Mint new tokens into an account from SYSTEM:ISSUANCE.

        The ISSUANCE account goes negative, representing total money supply.
        Returns the transaction_id.
        """
        if amount <= 0:
            raise ValueError(f"Mint amount must be positive, got {amount}")
        return await self.transfer(
            from_aid=SYSTEM_ISSUANCE,
            to_aid=to_aid,
            amount=amount,
            description=description or f"Mint {amount} AGC",
        )

    async def get_transaction_history(
        self,
        aid: str,
        limit: int = 50,
    ) -> list[LedgerEntry]:
        """Return ledger entries for an account, newest first."""
        async with self._connect() as db:
            cursor = await db.execute(
                """SELECT entry_id, transaction_id, timestamp, account,
                          direction, amount, balance_after, entry_type,
                          description
                   FROM ledger_entries
                   WHERE account = ?
                   ORDER BY timestamp DESC, rowid DESC
                   LIMIT ?""",
                (aid, limit),
            )
            rows = await cursor.fetchall()
            return [
                LedgerEntry(
                    entry_id=row[0],
                    transaction_id=row[1],
                    timestamp=row[2],
                    account=row[3],
                    direction=row[4],
                    amount=row[5],
                    balance_after=row[6],
                    entry_type=row[7],
                    description=row[8],
                )
                for row in rows
            ]


# ── Module-level convenience functions ───────────────────────


async def mint_tokens(
    db_path: Path, to_aid: str, amount: int, description: str = ""
) -> str:
    """Mint tokens using a one-shot Ledger instance."""
    ledger = Ledger(db_path)
    return await ledger.mint(to_aid, amount, description)


async def transfer(
    db_path: Path,
    from_aid: str,
    to_aid: str,
    amount: int,
    description: str = "",
) -> str:
    """Transfer tokens using a one-shot Ledger instance."""
    ledger = Ledger(db_path)
    return await ledger.transfer(from_aid, to_aid, amount, description)


async def get_balance(db_path: Path, aid: str) -> int:
    """Get balance using a one-shot Ledger instance."""
    ledger = Ledger(db_path)
    return await ledger.get_balance(aid)


__all__ = [
    "Ledger",
    "LedgerEntry",
    "mint_tokens",
    "transfer",
    "get_balance",
    "SYSTEM_ISSUANCE",
    "SYSTEM_ESCROW",
    "SYSTEM_BURN",
    "SYSTEM_FEES",
]
