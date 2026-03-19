"""Tests for the escrow module — exhaustive state transition coverage."""

from __future__ import annotations

import pytest

from ace.core.escrow import Escrow, EscrowManager
from ace.core.exceptions import InsufficientBalanceError, InvalidEscrowStateError
from ace.core.ledger import Ledger, SYSTEM_ESCROW


# ── Happy-path tests ────────────────────────────────────────


async def test_create_escrow_reduces_buyer_balance(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, ledger, buyer, seller = escrow_setup
    await em.create_escrow(buyer, seller, 500)
    assert await ledger.get_balance(buyer) == 9_500


async def test_create_escrow_increases_system_escrow_balance(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, ledger, buyer, seller = escrow_setup
    await em.create_escrow(buyer, seller, 500)
    assert await ledger.get_balance(SYSTEM_ESCROW) == 500


async def test_create_escrow_returns_uuid(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    escrow_id = await em.create_escrow(buyer, seller, 100)
    assert len(escrow_id) == 36  # UUID4 format


async def test_release_escrow_pays_seller(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, ledger, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 1_000)
    await em.release_escrow(eid)
    assert await ledger.get_balance(seller) == 11_000


async def test_release_escrow_state_becomes_released(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 1_000)
    await em.release_escrow(eid)
    escrow = await em.get_escrow(eid)
    assert escrow.state == "RELEASED"


async def test_release_escrow_sets_released_at(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 1_000)
    await em.release_escrow(eid)
    escrow = await em.get_escrow(eid)
    assert escrow.released_at is not None


async def test_refund_escrow_returns_funds_to_buyer(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, ledger, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 2_000)
    await em.refund_escrow(eid)
    assert await ledger.get_balance(buyer) == 10_000


async def test_refund_escrow_state_becomes_refunded(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 2_000)
    await em.refund_escrow(eid)
    escrow = await em.get_escrow(eid)
    assert escrow.state == "REFUNDED"


async def test_get_escrow_returns_correct_dataclass(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 750)
    escrow = await em.get_escrow(eid)
    assert isinstance(escrow, Escrow)
    assert escrow.escrow_id == eid
    assert escrow.buyer_aid == buyer
    assert escrow.seller_aid == seller
    assert escrow.amount == 750
    assert escrow.state == "LOCKED"
    assert escrow.released_at is None


# ── Invalid operations (security edge cases) ───────────────


async def test_cannot_release_already_released(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 500)
    await em.release_escrow(eid)
    with pytest.raises(InvalidEscrowStateError):
        await em.release_escrow(eid)


async def test_cannot_release_already_refunded(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 500)
    await em.refund_escrow(eid)
    with pytest.raises(InvalidEscrowStateError):
        await em.release_escrow(eid)


async def test_cannot_refund_already_released(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 500)
    await em.release_escrow(eid)
    with pytest.raises(InvalidEscrowStateError):
        await em.refund_escrow(eid)


async def test_cannot_refund_already_refunded(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 500)
    await em.refund_escrow(eid)
    with pytest.raises(InvalidEscrowStateError):
        await em.refund_escrow(eid)


async def test_create_escrow_insufficient_balance(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    with pytest.raises(InsufficientBalanceError):
        await em.create_escrow(buyer, seller, 99_999)


async def test_create_escrow_buyer_equals_seller(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, _ = escrow_setup
    with pytest.raises(ValueError, match="different"):
        await em.create_escrow(buyer, buyer, 100)


async def test_create_escrow_zero_amount(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    with pytest.raises(ValueError, match="positive"):
        await em.create_escrow(buyer, seller, 0)


async def test_create_escrow_negative_amount(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    with pytest.raises(ValueError, match="positive"):
        await em.create_escrow(buyer, seller, -100)


async def test_create_escrow_zero_timeout(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    with pytest.raises(ValueError, match="Timeout"):
        await em.create_escrow(buyer, seller, 100, timeout_seconds=0)


async def test_create_escrow_excessive_timeout(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    with pytest.raises(ValueError, match="Timeout"):
        await em.create_escrow(buyer, seller, 100, timeout_seconds=604_801)


async def test_get_escrow_not_found(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, _, _ = escrow_setup
    with pytest.raises(ValueError, match="not found"):
        await em.get_escrow("nonexistent-id")


async def test_release_escrow_not_found(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, _, _ = escrow_setup
    with pytest.raises(ValueError, match="not found"):
        await em.release_escrow("nonexistent-id")


async def test_refund_escrow_not_found(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, _, _ = escrow_setup
    with pytest.raises(ValueError, match="not found"):
        await em.refund_escrow("nonexistent-id")


# ── Timeout detection ───────────────────────────────────────


async def test_check_expired_finds_timed_out_escrow(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    # Create an escrow that's already expired (1 second timeout)
    eid = await em.create_escrow(buyer, seller, 100, timeout_seconds=1)

    # Force the timeout into the past via direct DB update
    import aiosqlite

    async with aiosqlite.connect(em._db_path) as db:  # noqa: SLF001
        await db.execute(
            "UPDATE escrows SET timeout_at = datetime('now', '-1 hour') "
            "WHERE escrow_id = ?",
            (eid,),
        )
        await db.commit()

    expired = await em.check_expired_escrows()
    assert eid in expired


async def test_check_expired_ignores_released(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 100, timeout_seconds=1)
    await em.release_escrow(eid)

    import aiosqlite

    async with aiosqlite.connect(em._db_path) as db:  # noqa: SLF001
        await db.execute(
            "UPDATE escrows SET timeout_at = datetime('now', '-1 hour') "
            "WHERE escrow_id = ?",
            (eid,),
        )
        await db.commit()

    expired = await em.check_expired_escrows()
    assert eid not in expired


async def test_check_expired_ignores_refunded(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 100, timeout_seconds=1)
    await em.refund_escrow(eid)

    import aiosqlite

    async with aiosqlite.connect(em._db_path) as db:  # noqa: SLF001
        await db.execute(
            "UPDATE escrows SET timeout_at = datetime('now', '-1 hour') "
            "WHERE escrow_id = ?",
            (eid,),
        )
        await db.commit()

    expired = await em.check_expired_escrows()
    assert eid not in expired


async def test_check_expired_ignores_future_timeout(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, _, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 100, timeout_seconds=3600)
    expired = await em.check_expired_escrows()
    assert eid not in expired


# ── Ledger integration / double-entry invariant ─────────────


async def test_double_entry_holds_after_create_and_release(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, ledger, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 3_000)
    await em.release_escrow(eid)

    # Buyer: 10000 - 3000 = 7000. Seller: 10000 + 3000 = 13000.
    assert await ledger.get_balance(buyer) == 7_000
    assert await ledger.get_balance(seller) == 13_000
    assert await ledger.get_balance(SYSTEM_ESCROW) == 0


async def test_double_entry_holds_after_create_and_refund(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, ledger, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 3_000)
    await em.refund_escrow(eid)

    # Buyer balance fully restored, seller unchanged
    assert await ledger.get_balance(buyer) == 10_000
    assert await ledger.get_balance(seller) == 10_000
    assert await ledger.get_balance(SYSTEM_ESCROW) == 0


async def test_system_escrow_zero_after_all_settled(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, ledger, buyer, seller = escrow_setup

    eid1 = await em.create_escrow(buyer, seller, 1_000)
    eid2 = await em.create_escrow(buyer, seller, 2_000)
    assert await ledger.get_balance(SYSTEM_ESCROW) == 3_000

    await em.release_escrow(eid1)
    await em.refund_escrow(eid2)
    assert await ledger.get_balance(SYSTEM_ESCROW) == 0


async def test_escrow_ledger_entries_use_correct_entry_types(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> None:
    em, ledger, buyer, seller = escrow_setup
    eid = await em.create_escrow(buyer, seller, 500)
    await em.release_escrow(eid)

    escrow_history = await ledger.get_transaction_history(SYSTEM_ESCROW)
    entry_types = {e.entry_type for e in escrow_history}
    assert "ESCROW_LOCK" in entry_types
    assert "ESCROW_RELEASE" in entry_types
