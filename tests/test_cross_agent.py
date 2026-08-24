"""Integration tests for the Agent-to-Agent HTTP protocol (Task 3).

Two separate create_app() instances (buyer + seller) connected via
httpx.MockTransport, which forwards buyer's async HTTP client to the
seller's synchronous TestClient — the same pattern used in
test_public_registry.py.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import aiosqlite
import httpx
import pytest
from fastapi.testclient import TestClient

from ace.api.server import create_app
from ace.core.config import AceSettings
from ace.core.identity import AgentIdentity
from ace.core.protocol import (
    EscrowProof,
    FundNotification,
    InboxMessage,
    InboxMessageType,
    canonical_json,
)

# ── Constants ────────────────────────────────────────────────

SELLER_URL = "http://test-seller"
BUYER_URL = "http://test-buyer"
SKILL_NAME = "test_skill"
SKILL_PRICE = 100


# ── Helpers ──────────────────────────────────────────────────


def _sign_post(
    tc: TestClient,
    path: str,
    body: dict[str, Any],
    identity: AgentIdentity,
    *,
    expected_status: int | None = None,
):
    """POST with Ed25519 signature using canonical JSON (sort_keys=True)."""
    body_bytes = canonical_json(body)
    sig = identity.sign(body_bytes)
    headers = {
        "X-Agent-ID": identity.aid,
        "X-Signature": base64.b64encode(sig).decode(),
        "Content-Type": "application/json",
    }
    resp = tc.post(path, content=body_bytes, headers=headers)
    if expected_status is not None:
        assert resp.status_code == expected_status, (
            f"Expected {expected_status}, got {resp.status_code}: {resp.text}"
        )
    return resp


def _forward_to_testclient(
    seller_tc: TestClient, seller_url: str, request: httpx.Request
) -> httpx.Response:
    """Forward an httpx.Request from buyer's AsyncClient to seller's TestClient."""
    base = seller_url.rstrip("/")
    path = str(request.url).replace(base, "")
    body = request.content
    fwd_headers: dict[str, str] = {}
    for key in ("content-type", "x-agent-id", "x-signature"):
        val = request.headers.get(key)
        if val:
            fwd_headers[key] = val
    resp = seller_tc.post(path, content=body, headers=fwd_headers)
    return httpx.Response(
        status_code=resp.status_code,
        headers=dict(resp.headers),
        content=resp.content,
    )


def _run(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine in a fresh event loop (for fixture setup)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _setup_agents(
    buyer_app,  # type: ignore[no-untyped-def]
    seller_app,
    buyer_identity: AgentIdentity,
    seller_identity: AgentIdentity,
) -> None:
    """Fund buyer, register agents on both sides, register seller's skill."""
    buyer_ledger = buyer_app.state.ledger
    seller_db_path = seller_app.state.db_path
    buyer_db_path = buyer_app.state.db_path

    # Fund buyer with plenty of tokens
    await buyer_ledger.mint(buyer_identity.aid, 100_000, "Cross-agent test funding")

    # Register buyer's public key on SELLER (so seller middleware accepts buyer's sigs)
    async with aiosqlite.connect(seller_db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO agents "
            "(aid, name, description, public_key, endpoint_url) VALUES (?, ?, ?, ?, ?)",
            (buyer_identity.aid, "buyer-agent", "", buyer_identity.public_key_b64, BUYER_URL),
        )
        await db.commit()

    # Register seller's public key on BUYER (not strictly required for this flow,
    # but good practice so buyer can later verify seller's signatures)
    async with aiosqlite.connect(buyer_db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO agents "
            "(aid, name, description, public_key, endpoint_url) VALUES (?, ?, ?, ?, ?)",
            (
                seller_identity.aid,
                "seller-agent",
                "",
                seller_identity.public_key_b64,
                SELLER_URL,
            ),
        )
        await db.commit()

    # Register test_skill in seller's skill_registry (price = SKILL_PRICE)
    async with aiosqlite.connect(seller_db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO skill_registry "
            "(aid, agent_card, name, description, price, tags) VALUES (?, ?, ?, ?, ?, ?)",
            (
                seller_identity.aid,
                json.dumps({"aid": seller_identity.aid}),
                SKILL_NAME,
                "A test capability",
                SKILL_PRICE,
                "",
            ),
        )
        await db.commit()


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture()
def buyer_identity() -> AgentIdentity:
    return AgentIdentity()


@pytest.fixture()
def seller_identity() -> AgentIdentity:
    return AgentIdentity()


@pytest.fixture()
def cross_agent_clients(
    tmp_path: Path,
    buyer_identity: AgentIdentity,
    seller_identity: AgentIdentity,
):
    """Provide two wired TestClients (buyer + seller) for cross-agent tests."""
    buyer_data = tmp_path / "buyer_data"
    buyer_data.mkdir()
    seller_data = tmp_path / "seller_data"
    seller_data.mkdir()

    buyer_settings = AceSettings(
        agent_name="buyer-agent",
        agent_description="",
        port=8081,
        data_dir=buyer_data,
    )
    seller_settings = AceSettings(
        agent_name="seller-agent",
        agent_description="",
        port=8082,
        data_dir=seller_data,
    )

    buyer_app = create_app(settings=buyer_settings, identity=buyer_identity)
    seller_app = create_app(settings=seller_settings, identity=seller_identity)

    with TestClient(seller_app) as seller_tc:
        with TestClient(buyer_app) as buyer_tc:
            # Wire buyer's async http_client to forward to seller's TestClient
            transport = httpx.MockTransport(
                lambda req: _forward_to_testclient(seller_tc, SELLER_URL, req)
            )
            buyer_app.state.http_client = httpx.AsyncClient(transport=transport)

            # Seed: fund buyer, register agents, register skill
            _run(_setup_agents(buyer_app, seller_app, buyer_identity, seller_identity))

            yield buyer_tc, seller_tc, buyer_identity, seller_identity


# ── Helper to run the full cross-agent lifecycle ─────────────


def _run_full_lifecycle(
    buyer_tc: TestClient,
    seller_tc: TestClient,
    buyer_identity: AgentIdentity,
    seller_identity: AgentIdentity,
) -> tuple[str, dict[str, Any]]:
    """Run create→accept→confirm and return (tx_id, final_tx_data)."""
    # Step 1: Buyer creates transaction with seller_url
    resp = _sign_post(
        buyer_tc,
        "/transactions/",
        {
            "seller_aid": seller_identity.aid,
            "capability_id": SKILL_NAME,
            "seller_url": SELLER_URL,
        },
        buyer_identity,
        expected_status=201,
    )
    tx_data = resp.json()["transaction"]
    tx_id = tx_data["tx_id"]
    assert tx_data["state"] == "QUOTED", f"Expected QUOTED after create, got: {tx_data['state']}"

    # Step 2: Buyer accepts quote (escrow locked + FundNotification sent)
    resp = _sign_post(
        buyer_tc,
        f"/transactions/{tx_id}/accept",
        {},
        buyer_identity,
        expected_status=200,
    )
    tx_data = resp.json()["transaction"]
    assert tx_data["state"] == "VERIFYING", (
        f"Expected VERIFYING after accept, got: {tx_data['state']}"
    )

    # Step 3: Buyer confirms (escrow→IOUS + ConfirmNotification sent)
    resp = _sign_post(
        buyer_tc,
        f"/transactions/{tx_id}/confirm",
        {},
        buyer_identity,
        expected_status=200,
    )
    tx_data = resp.json()["transaction"]
    assert tx_data["state"] == "SETTLED", (
        f"Expected SETTLED after confirm, got: {tx_data['state']}"
    )
    return tx_id, tx_data


# ── Tests ─────────────────────────────────────────────────────


class TestCrossAgentHappyPath:
    def test_full_cross_agent_lifecycle(self, cross_agent_clients):
        buyer_tc, seller_tc, buyer_identity, seller_identity = cross_agent_clients
        tx_id, tx_data = _run_full_lifecycle(
            buyer_tc, seller_tc, buyer_identity, seller_identity
        )
        assert tx_data["state"] == "SETTLED"
        assert tx_data["tx_id"] == tx_id

    def test_buyer_transaction_reaches_settled(self, cross_agent_clients):
        buyer_tc, seller_tc, buyer_identity, seller_identity = cross_agent_clients
        tx_id, _ = _run_full_lifecycle(buyer_tc, seller_tc, buyer_identity, seller_identity)

        # Fetch buyer's transaction directly
        resp = buyer_tc.get(f"/transactions/{tx_id}")
        assert resp.status_code == 200
        assert resp.json()["transaction"]["state"] == "SETTLED"

    def test_seller_mirror_transaction_settled(self, cross_agent_clients):
        buyer_tc, seller_tc, buyer_identity, seller_identity = cross_agent_clients
        tx_id, _ = _run_full_lifecycle(buyer_tc, seller_tc, buyer_identity, seller_identity)

        # Seller's mirror tx should also be SETTLED
        resp = seller_tc.get(f"/transactions/{tx_id}")
        assert resp.status_code == 200
        assert resp.json()["transaction"]["state"] == "SETTLED"

    def test_escrow_released_to_ious_not_seller(self, cross_agent_clients):
        buyer_tc, seller_tc, buyer_identity, seller_identity = cross_agent_clients
        _run_full_lifecycle(buyer_tc, seller_tc, buyer_identity, seller_identity)

        buyer_app = buyer_tc.app
        ious_balance = _run(buyer_app.state.ledger.get_balance("SYSTEM:IOUS"))
        assert ious_balance == SKILL_PRICE, (
            f"Expected SYSTEM:IOUS balance={SKILL_PRICE}, got {ious_balance}"
        )

    def test_iou_recorded_after_confirmation(self, cross_agent_clients):
        buyer_tc, seller_tc, buyer_identity, seller_identity = cross_agent_clients
        tx_id, _ = _run_full_lifecycle(buyer_tc, seller_tc, buyer_identity, seller_identity)

        seller_app = seller_tc.app
        debts = _run(seller_app.state.ledger.get_iou_debts(seller_identity.aid))
        assert len(debts) == 1
        d = debts[0]
        assert d.creditor_aid == seller_identity.aid
        assert d.debtor_aid == buyer_identity.aid
        assert d.amount == SKILL_PRICE
        assert d.tx_id == tx_id
        assert d.status == "PENDING"

    def test_receipt_hash_stored_correctly(self, cross_agent_clients):
        buyer_tc, seller_tc, buyer_identity, seller_identity = cross_agent_clients
        tx_id, _ = _run_full_lifecycle(buyer_tc, seller_tc, buyer_identity, seller_identity)

        seller_app = seller_tc.app
        debts = _run(seller_app.state.ledger.get_iou_debts(seller_identity.aid))
        assert len(debts) == 1
        # receipt_hash must be a valid sha256 hex string
        assert len(debts[0].receipt_hash) == 64
        assert all(c in "0123456789abcdef" for c in debts[0].receipt_hash)

    def test_admin_debts_endpoint(self, cross_agent_clients):
        buyer_tc, seller_tc, buyer_identity, seller_identity = cross_agent_clients
        _run_full_lifecycle(buyer_tc, seller_tc, buyer_identity, seller_identity)

        resp = seller_tc.get("/admin/debts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["debts"]) == 1
        assert data["debts"][0]["status"] == "PENDING"
        assert data["debts"][0]["amount"] == SKILL_PRICE


class TestCrossAgentSecurity:
    def test_bad_escrow_proof_signature_rejected(self, cross_agent_clients):
        """FundNotification with a tampered EscrowProof is rejected 403."""
        buyer_tc, seller_tc, buyer_identity, seller_identity = cross_agent_clients

        # First, create+quote transaction (so seller has a mirror tx)
        resp = _sign_post(
            buyer_tc,
            "/transactions/",
            {
                "seller_aid": seller_identity.aid,
                "capability_id": SKILL_NAME,
                "seller_url": SELLER_URL,
            },
            buyer_identity,
            expected_status=201,
        )
        tx_id = resp.json()["transaction"]["tx_id"]

        # Also, we need a real accept to get an escrow_id, but we'll fake it
        # by building a FundNotification with an invalid signature
        from datetime import UTC, datetime

        proof = EscrowProof(
            tx_id=tx_id,
            escrow_id="fake-escrow-00000000",
            buyer_aid=buyer_identity.aid,
            seller_aid=seller_identity.aid,
            amount=SKILL_PRICE,
            timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            signature=base64.b64encode(b"invalidsignature").decode(),
        )
        notif = FundNotification(tx_id=tx_id, escrow_proof=proof)
        msg = InboxMessage(
            message_type=InboxMessageType.FUND_NOTIFICATION,
            payload=notif.model_dump(),
        )
        # POST directly to seller's inbox (signed correctly at HTTP level)
        resp = _sign_post(
            seller_tc,
            "/agents/inbox",
            msg.model_dump(),
            buyer_identity,
        )
        assert resp.status_code == 403
        assert "EscrowProof" in resp.json()["error"]["message"]


class TestLocalTransactionUnaffected:
    """Verify that existing local (same-DB) transaction flow still works."""

    def test_local_transaction_lifecycle(self, tmp_path: Path):
        """Local transactions (no seller_url) work exactly as before."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        buyer_identity = AgentIdentity()
        seller_identity = AgentIdentity()

        settings = AceSettings(
            agent_name="test-agent",
            agent_description="",
            port=8080,
            data_dir=data_dir,
        )
        app = create_app(settings=settings, identity=buyer_identity)

        with TestClient(app) as tc:
            # Register seller in the same DB
            _run(app.state.ledger.create_account(seller_identity.aid))
            _run(app.state.ledger.mint(buyer_identity.aid, 10_000, "test"))

            import aiosqlite as _aio

            async def _register_seller():
                async with _aio.connect(app.state.db_path) as db:
                    await db.execute(
                        "INSERT OR IGNORE INTO agents "
                        "(aid, name, description, public_key, endpoint_url) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            seller_identity.aid,
                            "seller",
                            "",
                            seller_identity.public_key_b64,
                            "",
                        ),
                    )
                    await db.commit()

            _run(_register_seller())

            # Create (no seller_url) → state stays INITIATED
            body_bytes = json.dumps(
                {"seller_aid": seller_identity.aid, "capability_id": "cap1"},
                separators=(",", ":"),
            ).encode()
            sig = buyer_identity.sign(body_bytes)
            resp = tc.post(
                "/transactions/",
                content=body_bytes,
                headers={
                    "X-Agent-ID": buyer_identity.aid,
                    "X-Signature": base64.b64encode(sig).decode(),
                    "Content-Type": "application/json",
                },
            )
            assert resp.status_code == 201
            assert resp.json()["transaction"]["state"] == "INITIATED"
