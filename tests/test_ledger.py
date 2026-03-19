"""Comprehensive tests for the ledger module."""

from __future__ import annotations

import asyncio

import pytest

from ace.core.exceptions import AccountNotFoundError, InsufficientBalanceError
from ace.core.ledger import Ledger, LedgerEntry, SYSTEM_ISSUANCE


class TestAccountOperations:
    """Account creation and balance queries."""

    async def test_create_account_has_zero_balance(self, ledger: Ledger) -> None:
        await ledger.create_account("aid:testaccount")
        balance = await ledger.get_balance("aid:testaccount")
        assert balance == 0

    async def test_create_duplicate_account_raises(self, ledger: Ledger) -> None:
        await ledger.create_account("aid:duplicate")
        with pytest.raises(Exception):
            await ledger.create_account("aid:duplicate")

    async def test_get_balance_nonexistent_raises(self, ledger: Ledger) -> None:
        with pytest.raises(AccountNotFoundError):
            await ledger.get_balance("aid:nonexistent")


class TestMinting:
    """Token issuance from SYSTEM:ISSUANCE."""

    async def test_mint_increases_balance(self, ledger: Ledger) -> None:
        await ledger.create_account("aid:minter")
        await ledger.mint("aid:minter", 1000)
        assert await ledger.get_balance("aid:minter") == 1000

    async def test_mint_accumulates(self, ledger: Ledger) -> None:
        await ledger.create_account("aid:accum")
        await ledger.mint("aid:accum", 500)
        await ledger.mint("aid:accum", 300)
        assert await ledger.get_balance("aid:accum") == 800

    async def test_mint_to_nonexistent_raises(self, ledger: Ledger) -> None:
        with pytest.raises(AccountNotFoundError):
            await ledger.mint("aid:ghost", 500)

    async def test_issuance_goes_negative(self, ledger: Ledger) -> None:
        await ledger.create_account("aid:receiver")
        await ledger.mint("aid:receiver", 5000)
        assert await ledger.get_balance(SYSTEM_ISSUANCE) == -5000

    async def test_mint_zero_raises(self, ledger: Ledger) -> None:
        await ledger.create_account("aid:zero")
        with pytest.raises(ValueError):
            await ledger.mint("aid:zero", 0)

    async def test_mint_negative_raises(self, ledger: Ledger) -> None:
        await ledger.create_account("aid:neg")
        with pytest.raises(ValueError):
            await ledger.mint("aid:neg", -100)

    async def test_mint_returns_transaction_id(self, ledger: Ledger) -> None:
        await ledger.create_account("aid:txid")
        tx_id = await ledger.mint("aid:txid", 100)
        assert isinstance(tx_id, str)
        assert len(tx_id) == 36  # UUID4 format


class TestTransfers:
    """Transfer between two accounts — the critical path."""

    async def test_transfer_updates_both_balances(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        ledger, aid1, aid2 = two_funded_accounts
        await ledger.transfer(aid1, aid2, 3000, "test payment")
        assert await ledger.get_balance(aid1) == 7000
        assert await ledger.get_balance(aid2) == 13000

    async def test_transfer_insufficient_balance_raises(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        ledger, aid1, aid2 = two_funded_accounts
        with pytest.raises(InsufficientBalanceError):
            await ledger.transfer(aid1, aid2, 99999)

    async def test_transfer_zero_raises(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        ledger, aid1, aid2 = two_funded_accounts
        with pytest.raises(ValueError):
            await ledger.transfer(aid1, aid2, 0)

    async def test_transfer_negative_raises(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        ledger, aid1, aid2 = two_funded_accounts
        with pytest.raises(ValueError):
            await ledger.transfer(aid1, aid2, -50)

    async def test_transfer_to_self_raises(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        # Design decision: self-transfers are rejected to prevent
        # pointless ledger entries and potential confusion in history.
        ledger, aid1, _ = two_funded_accounts
        with pytest.raises(ValueError):
            await ledger.transfer(aid1, aid1, 100)

    async def test_transfer_nonexistent_sender_raises(self, ledger: Ledger) -> None:
        await ledger.create_account("aid:receiver")
        with pytest.raises(AccountNotFoundError):
            await ledger.transfer("aid:ghost", "aid:receiver", 100)

    async def test_transfer_nonexistent_receiver_raises(self, ledger: Ledger) -> None:
        await ledger.create_account("aid:sender")
        await ledger.mint("aid:sender", 1000)
        with pytest.raises(AccountNotFoundError):
            await ledger.transfer("aid:sender", "aid:ghost", 100)

    async def test_transfer_returns_transaction_id(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        ledger, aid1, aid2 = two_funded_accounts
        tx_id = await ledger.transfer(aid1, aid2, 100)
        assert isinstance(tx_id, str)
        assert len(tx_id) == 36

    async def test_failed_transfer_does_not_change_balances(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        ledger, aid1, aid2 = two_funded_accounts
        with pytest.raises(InsufficientBalanceError):
            await ledger.transfer(aid1, aid2, 99999)
        assert await ledger.get_balance(aid1) == 10000
        assert await ledger.get_balance(aid2) == 10000


class TestConcurrency:
    """Race condition and concurrent access tests."""

    async def test_concurrent_transfers_no_double_spend(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        """Two transfers that together exceed the balance: only one succeeds."""
        ledger, aid1, aid2 = two_funded_accounts
        # aid1 has 10,000. Two transfers of 7,000 each — only one can succeed.
        results = await asyncio.gather(
            ledger.transfer(aid1, aid2, 7000, "race-1"),
            ledger.transfer(aid1, aid2, 7000, "race-2"),
            return_exceptions=True,
        )
        successes = [r for r in results if isinstance(r, str)]
        failures = [r for r in results if isinstance(r, InsufficientBalanceError)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert await ledger.get_balance(aid1) == 3000
        assert await ledger.get_balance(aid2) == 17000

    async def test_concurrent_mints_all_succeed(self, ledger: Ledger) -> None:
        """10 concurrent mints of 100 each should all succeed."""
        await ledger.create_account("aid:concurrent")
        results = await asyncio.gather(
            *[ledger.mint("aid:concurrent", 100, f"mint-{i}") for i in range(10)]
        )
        assert all(isinstance(r, str) for r in results)
        assert await ledger.get_balance("aid:concurrent") == 1000


class TestDoubleEntryInvariant:
    """The golden rule: total DEBITs == total CREDITs."""

    @staticmethod
    async def _check_invariant(ledger: Ledger) -> None:
        """Assert the double-entry invariant holds across the entire ledger."""
        async with ledger._connect() as db:
            cursor = await db.execute(
                "SELECT direction, SUM(amount) FROM ledger_entries GROUP BY direction"
            )
            totals = {row[0]: row[1] for row in await cursor.fetchall()}
            debit_total = totals.get("DEBIT", 0)
            credit_total = totals.get("CREDIT", 0)
            assert debit_total == credit_total, (
                f"Double-entry invariant violated: DEBIT={debit_total} != CREDIT={credit_total}"
            )

    async def test_invariant_after_mint(self, ledger: Ledger) -> None:
        await ledger.create_account("aid:inv1")
        await ledger.mint("aid:inv1", 5000)
        await self._check_invariant(ledger)

    async def test_invariant_after_transfers(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        ledger, aid1, aid2 = two_funded_accounts
        await ledger.transfer(aid1, aid2, 3000)
        await ledger.transfer(aid2, aid1, 1000)
        await self._check_invariant(ledger)

    async def test_invariant_after_many_operations(self, ledger: Ledger) -> None:
        accounts = [f"aid:multi{i}" for i in range(5)]
        for aid in accounts:
            await ledger.create_account(aid)
            await ledger.mint(aid, 1000)
        for i in range(len(accounts) - 1):
            await ledger.transfer(accounts[i], accounts[i + 1], 200)
        await self._check_invariant(ledger)


class TestTransactionHistory:
    """Querying ledger entries for an account."""

    async def test_history_returns_entries(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        ledger, aid1, aid2 = two_funded_accounts
        await ledger.transfer(aid1, aid2, 500, "test tx")
        history = await ledger.get_transaction_history(aid1)
        assert len(history) > 0
        assert all(isinstance(e, LedgerEntry) for e in history)

    async def test_history_order_is_newest_first(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        ledger, aid1, aid2 = two_funded_accounts
        await ledger.transfer(aid1, aid2, 100, "first")
        await ledger.transfer(aid1, aid2, 200, "second")
        history = await ledger.get_transaction_history(aid1)
        # Most recent DEBIT entries for aid1
        descriptions = [e.description for e in history if e.direction == "DEBIT"]
        assert descriptions[0] == "second"
        assert descriptions[1] == "first"

    async def test_history_respects_limit(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        ledger, aid1, aid2 = two_funded_accounts
        for i in range(10):
            await ledger.transfer(aid1, aid2, 10, f"tx-{i}")
        history = await ledger.get_transaction_history(aid1, limit=3)
        assert len(history) == 3

    async def test_history_nonexistent_returns_empty(self, ledger: Ledger) -> None:
        history = await ledger.get_transaction_history("aid:ghost")
        assert history == []

    async def test_history_entry_fields_populated(
        self, two_funded_accounts: tuple[Ledger, str, str]
    ) -> None:
        ledger, aid1, aid2 = two_funded_accounts
        tx_id = await ledger.transfer(aid1, aid2, 100, "field check")
        history = await ledger.get_transaction_history(aid1, limit=1)
        entry = history[0]
        assert entry.transaction_id == tx_id
        assert entry.account == aid1
        assert entry.direction == "DEBIT"
        assert entry.amount == 100
        assert entry.entry_type == "TRANSFER"
        assert entry.description == "field check"
        assert entry.balance_after == 9900
