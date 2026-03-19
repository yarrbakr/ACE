"""API endpoint tests for the registry service."""

from __future__ import annotations

from fastapi.testclient import TestClient

from registry.tests.conftest import SAMPLE_AGENT_CARD, SAMPLE_AGENT_CARD_2


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


def test_register_agent_201(registry_client: TestClient) -> None:
    resp = registry_client.post(
        "/register",
        json={"aid": "aid:test1", "agent_card": SAMPLE_AGENT_CARD},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "ok"
    assert data["aid"] == "aid:test1"
    assert data["registered"] is True


def test_register_agent_upsert(registry_client: TestClient) -> None:
    registry_client.post(
        "/register",
        json={"aid": "aid:test1", "agent_card": SAMPLE_AGENT_CARD},
    )
    updated = {**SAMPLE_AGENT_CARD, "name": "updated-name"}
    resp = registry_client.post(
        "/register",
        json={"aid": "aid:test1", "agent_card": updated},
    )
    assert resp.status_code == 201
    # Verify update took effect
    get_resp = registry_client.get("/agents/aid:test1")
    assert get_resp.json()["agent"]["name"] == "updated-name"


# ── Deregistration ─────────────────────────────────────────


def test_deregister_agent(registry_client: TestClient) -> None:
    registry_client.post(
        "/register",
        json={"aid": "aid:test1", "agent_card": SAMPLE_AGENT_CARD},
    )
    resp = registry_client.post("/deregister", json={"aid": "aid:test1"})
    assert resp.status_code == 200
    assert resp.json()["deregistered"] is True


def test_deregister_not_found_404(registry_client: TestClient) -> None:
    resp = registry_client.post("/deregister", json={"aid": "aid:nonexistent"})
    assert resp.status_code == 404
    assert resp.json()["status"] == "error"


# ── Heartbeat ──────────────────────────────────────────────


def test_heartbeat_ok(registry_client: TestClient) -> None:
    registry_client.post(
        "/register",
        json={"aid": "aid:test1", "agent_card": SAMPLE_AGENT_CARD},
    )
    resp = registry_client.post("/heartbeat", json={"aid": "aid:test1"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_heartbeat_not_found_404(registry_client: TestClient) -> None:
    resp = registry_client.post("/heartbeat", json={"aid": "aid:missing"})
    assert resp.status_code == 404


# ── Search ─────────────────────────────────────────────────


def test_search_returns_results(registry_client: TestClient) -> None:
    registry_client.post(
        "/register",
        json={"aid": "aid:test1", "agent_card": SAMPLE_AGENT_CARD},
    )
    resp = registry_client.get("/search", params={"q": "code review"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert len(data["results"]) >= 1


def test_search_empty_results(registry_client: TestClient) -> None:
    resp = registry_client.get("/search", params={"q": "nonexistent"})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_search_max_price(registry_client: TestClient) -> None:
    registry_client.post(
        "/register",
        json={"aid": "aid:test1", "agent_card": SAMPLE_AGENT_CARD},
    )
    registry_client.post(
        "/register",
        json={"aid": "aid:test2", "agent_card": SAMPLE_AGENT_CARD_2},
    )
    # Only results with price <= 40
    resp = registry_client.get(
        "/search", params={"q": "python translation", "max_price": 40}
    )
    data = resp.json()
    for result in data["results"]:
        assert result["price"] <= 40


# ── Agent Listing ──────────────────────────────────────────


def test_list_agents(registry_client: TestClient) -> None:
    registry_client.post(
        "/register",
        json={"aid": "aid:test1", "agent_card": SAMPLE_AGENT_CARD},
    )
    registry_client.post(
        "/register",
        json={"aid": "aid:test2", "agent_card": SAMPLE_AGENT_CARD_2},
    )
    resp = registry_client.get("/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2


def test_get_agent_by_aid(registry_client: TestClient) -> None:
    registry_client.post(
        "/register",
        json={"aid": "aid:test1", "agent_card": SAMPLE_AGENT_CARD},
    )
    resp = registry_client.get("/agents/aid:test1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent"]["name"] == "test-agent"


def test_get_agent_not_found_404(registry_client: TestClient) -> None:
    resp = registry_client.get("/agents/aid:doesnotexist")
    assert resp.status_code == 404
    assert resp.json()["status"] == "error"
