"""Tests for the FastAPI API layer — integration tests via TestClient.

Covers: Agent Card, transaction lifecycle, discovery, admin, and
signature verification security.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from ace.api.server import create_app
from ace.core.config import AceSettings
from ace.core.identity import AgentIdentity
from ace.core.ledger import Ledger


# ── Helpers ─────────────────────────────────────────────────


def _sign_and_post(
    tc: TestClient,
    path: str,
    body: dict,
    identity: AgentIdentity,
    *,
    expected_status: int | None = None,
):
    """POST with correct Ed25519 signature over the exact body bytes."""
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
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


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture()
def test_settings(tmp_path: Path) -> AceSettings:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return AceSettings(
        agent_name="test-agent",
        agent_description="A test agent",
        port=8080,
        data_dir=data_dir,
    )


@pytest.fixture()
def buyer_identity() -> AgentIdentity:
    return AgentIdentity()


@pytest.fixture()
def seller_identity() -> AgentIdentity:
    return AgentIdentity()


@pytest.fixture()
def client(test_settings: AceSettings, buyer_identity: AgentIdentity):
    """TestClient with buyer identity — lifespan runs via context manager."""
    app = create_app(settings=test_settings, identity=buyer_identity)
    with TestClient(app) as tc:
        yield tc


@pytest.fixture()
def funded_client(
    test_settings: AceSettings,
    buyer_identity: AgentIdentity,
    seller_identity: AgentIdentity,
):
    """TestClient with both buyer and seller funded + seller registered."""
    import asyncio

    app = create_app(settings=test_settings, identity=buyer_identity)

    with TestClient(app) as tc:
        async def _setup():
            ledger: Ledger = app.state.ledger
            await ledger.create_account(seller_identity.aid)
            await ledger.mint(buyer_identity.aid, 100_000, "Test funding")
            await ledger.mint(seller_identity.aid, 100_000, "Test funding")

            db_path = app.state.db_path
            async with aiosqlite.connect(db_path) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA foreign_keys=ON")
                await db.execute(
                    """INSERT OR IGNORE INTO agents
                       (aid, name, description, public_key)
                       VALUES (?, ?, ?, ?)""",
                    (
                        seller_identity.aid,
                        "test-seller",
                        "Seller agent",
                        seller_identity.public_key_b64,
                    ),
                )
                await db.commit()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_setup())
        loop.close()

        yield tc, buyer_identity, seller_identity


# ── Agent Card Tests ────────────────────────────────────────


class TestAgentCard:
    def test_well_known_agent_json(self, client: TestClient) -> None:
        resp = client.get("/.well-known/agent.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-agent"
        assert data["aid"].startswith("aid:")
        assert data["authentication"]["type"] == "ed25519"
        assert data["authentication"]["public_key"] != ""

    def test_agent_card_has_capabilities_list(self, client: TestClient) -> None:
        data = client.get("/.well-known/agent.json").json()
        assert isinstance(data["capabilities"], list)

    def test_agent_card_has_url(self, client: TestClient) -> None:
        data = client.get("/.well-known/agent.json").json()
        assert "8080" in data["url"]

    def test_agent_card_uses_public_url(
        self, tmp_path: Path, buyer_identity: AgentIdentity
    ) -> None:
        """When public_url is set, agent card returns it instead of localhost."""
        data_dir = tmp_path / "data2"
        data_dir.mkdir()
        settings = AceSettings(
            agent_name="test-agent",
            agent_description="A test agent",
            port=8080,
            data_dir=data_dir,
            public_url="https://my-agent.example.com",
        )
        app = create_app(settings=settings, identity=buyer_identity)
        with TestClient(app) as tc:
            resp = tc.get("/.well-known/agent.json")
            assert resp.status_code == 200
            assert resp.json()["url"] == "https://my-agent.example.com"

    def test_agent_card_falls_back_to_localhost(self, client: TestClient) -> None:
        """When public_url is empty, agent card falls back to localhost:port."""
        data = client.get("/.well-known/agent.json").json()
        assert "127.0.0.1" in data["url"]


# ── Health Check ────────────────────────────────────────────


class TestHealth:
    def test_health_endpoint(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── Transaction Lifecycle Tests ─────────────────────────────


class TestTransactions:
    def test_create_transaction(self, funded_client) -> None:
        tc, buyer, seller = funded_client
        body = {"seller_aid": seller.aid, "capability_id": "test_skill"}
        resp = _sign_and_post(tc, "/transactions/", body, buyer, expected_status=201)
        data = resp.json()
        assert data["transaction"]["state"] == "INITIATED"
        assert data["transaction"]["buyer_aid"] == buyer.aid

    def test_create_transaction_invalid_body(self, funded_client) -> None:
        tc, buyer, _ = funded_client
        body = {"bad_field": "nope"}
        resp = _sign_and_post(tc, "/transactions/", body, buyer)
        assert resp.status_code == 422

    def test_get_transaction(self, funded_client) -> None:
        tc, buyer, seller = funded_client
        body = {"seller_aid": seller.aid, "capability_id": "test_skill"}
        resp = _sign_and_post(tc, "/transactions/", body, buyer, expected_status=201)
        tx_id = resp.json()["transaction"]["tx_id"]

        get_resp = tc.get(f"/transactions/{tx_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["transaction"]["tx_id"] == tx_id

    def test_get_nonexistent_transaction(self, client: TestClient) -> None:
        resp = client.get("/transactions/nonexistent-tx-id")
        assert resp.status_code == 404

    def test_full_lifecycle(self, funded_client) -> None:
        """create → quote → accept → deliver → confirm → SETTLED"""
        tc, buyer, seller = funded_client

        # 1. create
        body = {"seller_aid": seller.aid, "capability_id": "test_skill"}
        resp = _sign_and_post(tc, "/transactions/", body, buyer, expected_status=201)
        tx_id = resp.json()["transaction"]["tx_id"]

        # 2. quote
        resp = _sign_and_post(
            tc, f"/transactions/{tx_id}/quote", {"price": 100}, seller, expected_status=200
        )
        assert resp.json()["transaction"]["state"] == "QUOTED"

        # 3. accept
        resp = _sign_and_post(
            tc, f"/transactions/{tx_id}/accept", {}, buyer, expected_status=200
        )
        assert resp.json()["transaction"]["state"] == "EXECUTING"

        # 4. deliver
        resp = _sign_and_post(
            tc, f"/transactions/{tx_id}/deliver",
            {"result_hash": "abc123hash"}, seller, expected_status=200,
        )
        assert resp.json()["transaction"]["state"] == "VERIFYING"

        # 5. confirm
        resp = _sign_and_post(
            tc, f"/transactions/{tx_id}/confirm", {}, buyer, expected_status=200,
        )
        assert resp.json()["transaction"]["state"] == "SETTLED"

    def test_list_transactions(self, funded_client) -> None:
        tc, buyer, seller = funded_client
        body = {"seller_aid": seller.aid, "capability_id": "test_skill"}
        _sign_and_post(tc, "/transactions/", body, buyer, expected_status=201)

        resp = tc.get("/transactions/")
        assert resp.status_code == 200
        assert len(resp.json()["transactions"]) >= 1

    def test_dispute_flow(self, funded_client) -> None:
        """create → quote → accept → deliver → dispute → DISPUTED"""
        tc, buyer, seller = funded_client

        body = {"seller_aid": seller.aid, "capability_id": "test_skill"}
        resp = _sign_and_post(tc, "/transactions/", body, buyer, expected_status=201)
        tx_id = resp.json()["transaction"]["tx_id"]

        _sign_and_post(tc, f"/transactions/{tx_id}/quote", {"price": 50}, seller)
        _sign_and_post(tc, f"/transactions/{tx_id}/accept", {}, buyer)
        _sign_and_post(
            tc, f"/transactions/{tx_id}/deliver", {"result_hash": "badhash"}, seller,
        )

        resp = _sign_and_post(
            tc, f"/transactions/{tx_id}/dispute",
            {"reason": "Result was wrong"}, buyer,
            expected_status=200,
        )
        assert resp.json()["transaction"]["state"] == "DISPUTED"


# ── Discovery Tests ─────────────────────────────────────────


class TestDiscovery:
    def test_search_returns_empty(self, client: TestClient) -> None:
        resp = client.get("/discovery/search?q=nonexistent_capability")
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_list_agents(self, client: TestClient) -> None:
        resp = client.get("/discovery/agents")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ── Admin Tests ─────────────────────────────────────────────


class TestAdmin:
    def test_balance(self, client: TestClient) -> None:
        resp = client.get("/admin/balance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "balance" in data

    def test_status(self, client: TestClient) -> None:
        resp = client.get("/admin/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["agent_name"] == "test-agent"
        assert data["skills_count"] >= 0

    def test_history(self, client: TestClient) -> None:
        resp = client.get("/admin/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "entries" in data


# ── Security Tests ──────────────────────────────────────────


class TestSecurity:
    def test_unsigned_post_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/transactions/",
            json={"seller_aid": "aid:xxx", "capability_id": "x"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    def test_missing_signature_header(
        self, client: TestClient, buyer_identity: AgentIdentity
    ) -> None:
        resp = client.post(
            "/transactions/",
            json={"seller_aid": "aid:xxx", "capability_id": "x"},
            headers={"X-Agent-ID": buyer_identity.aid},
        )
        assert resp.status_code == 401
        assert "X-Signature" in resp.json()["error"]["message"]

    def test_wrong_signature_rejected(
        self, client: TestClient, buyer_identity: AgentIdentity
    ) -> None:
        resp = client.post(
            "/transactions/",
            json={"seller_aid": "aid:xxx", "capability_id": "x"},
            headers={
                "X-Agent-ID": buyer_identity.aid,
                "X-Signature": base64.b64encode(b"invalid_sig_bytes").decode(),
            },
        )
        assert resp.status_code == 403

    def test_unknown_agent_id_rejected(self, client: TestClient) -> None:
        other = AgentIdentity()
        body = {"seller_aid": "aid:xxx", "capability_id": "x"}
        resp = _sign_and_post(client, "/transactions/", body, other)
        assert resp.status_code == 401
        assert "Unknown agent" in resp.json()["error"]["message"]

    def test_get_requires_no_signature(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200
        assert client.get("/.well-known/agent.json").status_code == 200

    def test_valid_signature_succeeds(self, funded_client) -> None:
        tc, buyer, seller = funded_client
        body = {"seller_aid": seller.aid, "capability_id": "test_skill"}
        resp = _sign_and_post(tc, "/transactions/", body, buyer)
        assert resp.status_code == 201
