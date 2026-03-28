"""API endpoint tests for the registry service."""

from __future__ import annotations

import base64
import json
from typing import Any

from fastapi.testclient import TestClient

from ace.core.identity import AgentIdentity
from registry.routes import _rate_limit
from registry.tests.conftest import (
    SAMPLE_AGENT_CARD_2,
    SAMPLE_AGENT_CARD_2_IDENTITY,
    make_agent_card,
    signed_post,
)


def _register_agent(
    tc: TestClient, identity: AgentIdentity, *, name: str = "test-agent"
) -> dict[str, Any]:
    """Helper: register an agent and return the agent card used."""
    card = make_agent_card(identity, name=name)
    signed_post(
        tc, "/register", {"aid": identity.aid, "agent_card": card}, identity, expected_status=201
    )
    return card


# ── Health ─────────────────────────────────────────────────


def test_health_endpoint(registry_client: TestClient) -> None:
    resp = registry_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert data["agent_count"] == 0
    assert data["uptime_seconds"] >= 0


# ── Registration ───────────────────────────────────────────


def test_register_agent_201(registry_client: TestClient, registry_identity: AgentIdentity) -> None:
    card = make_agent_card(registry_identity)
    resp = signed_post(
        registry_client,
        "/register",
        {"aid": registry_identity.aid, "agent_card": card},
        registry_identity,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "ok"
    assert data["aid"] == registry_identity.aid
    assert data["registered"] is True


def test_register_agent_upsert(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    card = make_agent_card(registry_identity)
    signed_post(
        registry_client,
        "/register",
        {"aid": registry_identity.aid, "agent_card": card},
        registry_identity,
        expected_status=201,
    )
    updated_card = {**card, "name": "updated-name"}
    signed_post(
        registry_client,
        "/register",
        {"aid": registry_identity.aid, "agent_card": updated_card},
        registry_identity,
        expected_status=201,
    )
    get_resp = registry_client.get(f"/agents/{registry_identity.aid}")
    assert get_resp.json()["agent"]["name"] == "updated-name"


# ── Deregistration ─────────────────────────────────────────


def test_deregister_agent(registry_client: TestClient, registry_identity: AgentIdentity) -> None:
    _register_agent(registry_client, registry_identity)
    resp = signed_post(
        registry_client,
        "/deregister",
        {"aid": registry_identity.aid},
        registry_identity,
    )
    assert resp.status_code == 200
    assert resp.json()["deregistered"] is True


def test_deregister_not_found_404(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    resp = signed_post(
        registry_client,
        "/deregister",
        {"aid": registry_identity.aid},
        registry_identity,
    )
    assert resp.status_code == 404
    assert resp.json()["status"] == "error"


# ── Heartbeat ──────────────────────────────────────────────


def test_heartbeat_ok(registry_client: TestClient, registry_identity: AgentIdentity) -> None:
    _register_agent(registry_client, registry_identity)
    resp = signed_post(
        registry_client,
        "/heartbeat",
        {"aid": registry_identity.aid},
        registry_identity,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_heartbeat_not_found_404(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    resp = signed_post(
        registry_client,
        "/heartbeat",
        {"aid": registry_identity.aid},
        registry_identity,
    )
    assert resp.status_code == 404


# ── Search ─────────────────────────────────────────────────


def test_search_returns_results(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    _register_agent(registry_client, registry_identity)
    resp = registry_client.get("/search", params={"q": "code review"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert len(data["results"]) >= 1


def test_search_empty_results(registry_client: TestClient) -> None:
    resp = registry_client.get("/search", params={"q": "nonexistent"})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_search_max_price(registry_client: TestClient, registry_identity: AgentIdentity) -> None:
    _register_agent(registry_client, registry_identity)
    signed_post(
        registry_client,
        "/register",
        {"aid": SAMPLE_AGENT_CARD_2["aid"], "agent_card": SAMPLE_AGENT_CARD_2},
        SAMPLE_AGENT_CARD_2_IDENTITY,
        expected_status=201,
    )
    resp = registry_client.get("/search", params={"q": "python translation", "max_price": 40})
    data = resp.json()
    for result in data["results"]:
        assert result["price"] <= 40


# ── Agent Listing ──────────────────────────────────────────


def test_list_agents(registry_client: TestClient, registry_identity: AgentIdentity) -> None:
    _register_agent(registry_client, registry_identity)
    signed_post(
        registry_client,
        "/register",
        {"aid": SAMPLE_AGENT_CARD_2["aid"], "agent_card": SAMPLE_AGENT_CARD_2},
        SAMPLE_AGENT_CARD_2_IDENTITY,
        expected_status=201,
    )
    resp = registry_client.get("/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2


def test_get_agent_by_aid(registry_client: TestClient, registry_identity: AgentIdentity) -> None:
    _register_agent(registry_client, registry_identity)
    resp = registry_client.get(f"/agents/{registry_identity.aid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent"]["name"] == "test-agent"


def test_get_agent_not_found_404(registry_client: TestClient) -> None:
    resp = registry_client.get("/agents/aid:doesnotexist")
    assert resp.status_code == 404
    assert resp.json()["status"] == "error"


# ── Rate Limiting ──────────────────────────────────────────


def test_register_rate_limited(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    _rate_limit.clear()
    card = make_agent_card(registry_identity)
    for i in range(10):
        resp = signed_post(
            registry_client,
            "/register",
            {"aid": registry_identity.aid, "agent_card": card},
            registry_identity,
        )
        assert resp.status_code == 201, f"Request {i + 1} failed unexpectedly"

    # 11th should be rate limited
    resp = signed_post(
        registry_client,
        "/register",
        {"aid": registry_identity.aid, "agent_card": card},
        registry_identity,
    )
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMITED"


def test_search_rate_limited(registry_client: TestClient) -> None:
    _rate_limit.clear()
    for i in range(60):
        resp = registry_client.get("/search", params={"q": "test"})
        assert resp.status_code == 200, f"Request {i + 1} failed unexpectedly"

    # 61st should be rate limited
    resp = registry_client.get("/search", params={"q": "test"})
    data = resp.json()
    assert data["status"] == "error"


# ── Size Limits ────────────────────────────────────────────


def test_register_oversized_agent_card(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    big_card = make_agent_card(registry_identity)
    big_card["huge_field"] = "x" * 70_000  # > 64KB
    payload = {"aid": registry_identity.aid, "agent_card": big_card}
    body_bytes = json.dumps(payload, separators=(",", ":")).encode()
    sig = registry_identity.sign(body_bytes)
    resp = registry_client.post(
        "/register",
        content=body_bytes,
        headers={
            "X-Agent-ID": registry_identity.aid,
            "X-Signature": base64.b64encode(sig).decode(),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 422  # Pydantic validation error


def test_register_oversized_aid(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    card = make_agent_card(registry_identity)
    long_aid = "aid:" + "a" * 260
    payload = {"aid": long_aid, "agent_card": card}
    body_bytes = json.dumps(payload, separators=(",", ":")).encode()
    sig = registry_identity.sign(body_bytes)
    resp = registry_client.post(
        "/register",
        content=body_bytes,
        headers={
            "X-Agent-ID": registry_identity.aid,
            "X-Signature": base64.b64encode(sig).decode(),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 422  # Pydantic validation error


# ── Signature Verification ─────────────────────────────────


def test_register_missing_signature(registry_client: TestClient) -> None:
    resp = registry_client.post(
        "/register",
        json={"aid": "aid:test", "agent_card": {"name": "test"}},
    )
    assert resp.status_code == 401
    assert "X-Agent-ID" in resp.json()["error"]["message"]


def test_register_missing_x_signature_header(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    card = make_agent_card(registry_identity)
    resp = registry_client.post(
        "/register",
        json={"aid": registry_identity.aid, "agent_card": card},
        headers={"X-Agent-ID": registry_identity.aid},
    )
    assert resp.status_code == 401
    assert "X-Signature" in resp.json()["error"]["message"]


def test_register_invalid_signature(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    _rate_limit.clear()
    card = make_agent_card(registry_identity)
    payload = {"aid": registry_identity.aid, "agent_card": card}
    body_bytes = json.dumps(payload, separators=(",", ":")).encode()
    resp = registry_client.post(
        "/register",
        content=body_bytes,
        headers={
            "X-Agent-ID": registry_identity.aid,
            "X-Signature": base64.b64encode(b"invalid_sig_bytes").decode(),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_register_valid_signature(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    _rate_limit.clear()
    card = make_agent_card(registry_identity)
    resp = signed_post(
        registry_client,
        "/register",
        {"aid": registry_identity.aid, "agent_card": card},
        registry_identity,
    )
    assert resp.status_code == 201


def test_deregister_valid_signature(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    _rate_limit.clear()
    _register_agent(registry_client, registry_identity)
    resp = signed_post(
        registry_client,
        "/deregister",
        {"aid": registry_identity.aid},
        registry_identity,
    )
    assert resp.status_code == 200
    assert resp.json()["deregistered"] is True


def test_heartbeat_valid_signature(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    _rate_limit.clear()
    _register_agent(registry_client, registry_identity)
    resp = signed_post(
        registry_client,
        "/heartbeat",
        {"aid": registry_identity.aid},
        registry_identity,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_deregister_wrong_identity_rejected(
    registry_client: TestClient, registry_identity: AgentIdentity
) -> None:
    """An attacker can't deregister someone else's agent."""
    _rate_limit.clear()
    _register_agent(registry_client, registry_identity)
    attacker = AgentIdentity()
    # Attacker signs with their own key but claims to be the victim
    payload = {"aid": registry_identity.aid}
    body_bytes = json.dumps(payload, separators=(",", ":")).encode()
    sig = attacker.sign(body_bytes)
    resp = registry_client.post(
        "/deregister",
        content=body_bytes,
        headers={
            "X-Agent-ID": registry_identity.aid,
            "X-Signature": base64.b64encode(sig).decode(),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 403
