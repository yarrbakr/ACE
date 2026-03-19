"""Shared test fixtures for the ACE test suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ace.cli.main import app
from ace.core.escrow import EscrowManager
from ace.core.identity import AgentIdentity
from ace.core.ledger import Ledger
from ace.core.transaction import TransactionEngine

TEST_PASSWORD = "super-secret-test-pw-123"


@pytest.fixture()
def cli_runner() -> CliRunner:
    """Provide a Typer CliRunner for invoking CLI commands."""
    return CliRunner()


@pytest.fixture()
def tmp_ace_dir(tmp_path: Path) -> Path:
    """Provide a temporary ~/.ace directory for isolated testing."""
    ace_dir = tmp_path / ".ace"
    ace_dir.mkdir()
    data_dir = ace_dir / "data"
    data_dir.mkdir()
    return ace_dir


@pytest.fixture()
def ace_app():
    """Provide the Typer app instance for CLI testing."""
    return app


@pytest.fixture()
def identity() -> AgentIdentity:
    """Provide a fresh AgentIdentity for testing."""
    return AgentIdentity()


@pytest.fixture()
def password() -> str:
    """Provide a consistent test password."""
    return TEST_PASSWORD


@pytest.fixture()
def encrypted_key_path(tmp_path: Path, identity: AgentIdentity, password: str) -> Path:
    """Provide a saved encrypted identity key file."""
    key_path = tmp_path / "identity.key"
    identity.save_encrypted(key_path, password)
    return key_path


# ── Ledger fixtures ──────────────────────────────────────────


@pytest.fixture()
def tmp_db_path(tmp_path: Path) -> Path:
    """Provide a path for a temporary SQLite database."""
    return tmp_path / "test_ace.db"


@pytest.fixture()
async def ledger(tmp_db_path: Path) -> Ledger:
    """Provide an initialized Ledger instance with a fresh database."""
    _ledger = Ledger(tmp_db_path)
    await _ledger.initialize()
    return _ledger


@pytest.fixture()
async def two_funded_accounts(ledger: Ledger) -> tuple[Ledger, str, str]:
    """Provide a ledger with two accounts, each holding 10,000 AGC."""
    aid1 = "aid:testagent1aaaaaa"
    aid2 = "aid:testagent2bbbbbb"
    await ledger.create_account(aid1)
    await ledger.create_account(aid2)
    await ledger.mint(aid1, 10_000, "Test funding")
    await ledger.mint(aid2, 10_000, "Test funding")
    return ledger, aid1, aid2


# ── Escrow fixtures ─────────────────────────────────────────


@pytest.fixture()
async def escrow_manager(ledger: Ledger) -> EscrowManager:
    """Provide an EscrowManager backed by the test ledger."""
    return EscrowManager(ledger)


@pytest.fixture()
async def escrow_setup(
    two_funded_accounts: tuple[Ledger, str, str],
) -> tuple[EscrowManager, Ledger, str, str]:
    """Provide an EscrowManager with two funded accounts (10,000 AGC each)."""
    ledger, buyer, seller = two_funded_accounts
    return EscrowManager(ledger), ledger, buyer, seller


# ── Transaction fixtures ────────────────────────────────────


@pytest.fixture()
async def transaction_engine(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> TransactionEngine:
    """Provide a TransactionEngine backed by ledger + escrow with funded accounts."""
    escrow_mgr, ledger, _, _ = escrow_setup
    return TransactionEngine(ledger, escrow_mgr)


@pytest.fixture()
async def tx_setup(
    escrow_setup: tuple[EscrowManager, Ledger, str, str],
) -> tuple[TransactionEngine, Ledger, str, str]:
    """Provide a TransactionEngine + ledger + buyer_aid + seller_aid."""
    escrow_mgr, ledger, buyer, seller = escrow_setup
    engine = TransactionEngine(ledger, escrow_mgr)
    return engine, ledger, buyer, seller
