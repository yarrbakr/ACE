"""Integration tests for PublicRegistryDiscovery adapter against a real registry."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from ace.core.identity import AgentIdentity
from ace.discovery.public_registry import PublicRegistryDiscovery
from registry.app import create_registry_app
from registry.routes import _rate_limit

# ── Identities & sample cards ─────────────────────────────

_IDENTITY_1 = AgentIdentity()
_IDENTITY_2 = AgentIdentity()


def _make_card(
    identity: AgentIdentity,
    name: str = "test-agent",
    description: str = "An agent for adapter tests",
    url: str = "http://localhost:8080",
    capabilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if capabilities is None:
        capabilities = [
            {
                "id": "code_review",
                "name": "Code Review",
                "description": "Reviews Python code for quality",
                "pricing": {"currency": "AGC", "model": "per_call", "amount": 50},
                "tags": ["python", "review"],
            }
        ]
    return {
        "name": name,
        "description": description,
        "url": url,
        "capabilities": capabilities,
        "authentication": {"type": "ed25519", "public_key": identity.public_key_b64},
        "aid": identity.aid,
    }


SAMPLE_CARD: dict[str, Any] = _make_card(_IDENTITY_1)

SAMPLE_CARD_2: dict[str, Any] = _make_card(
    _IDENTITY_2,
    name="translator-agent",
    description="Translates text",
    url="http://localhost:8081",
    capabilities=[
        {
            "id": "translate",
            "name": "Translation",
            "description": "Translates text between languages",
            "pricing": {"currency": "AGC", "model": "per_call", "amount": 30},
            "tags": ["translation", "nlp"],
        }
    ],
)


# ── Helpers ────────────────────────────────────────────────


def _forward_to_testclient(
    tc: TestClient, request: httpx.Request
) -> httpx.Response:
    """Forward an httpx Request to a FastAPI TestClient, preserving signature headers."""
    url = str(request.url)
    path = url.replace("http://testregistry", "")
    body = request.content

    # Forward signing headers for registry signature verification
    fwd_headers: dict[str, str] = {}
    for key in ("content-type", "x-agent-id", "x-signature"):
        val = request.headers.get(key)
        if val:
            fwd_headers[key] = val

    if request.method == "GET":
        resp = tc.get(path)
    elif request.method == "POST":
        resp = tc.post(path, content=body, headers=fwd_headers)
    else:
        resp = tc.request(request.method, path, content=body)

    return httpx.Response(
        status_code=resp.status_code,
        headers=dict(resp.headers),
        content=resp.content,
    )


def _make_adapter(
    tc: TestClient, identity: AgentIdentity, *, heartbeat_interval: float = 9999.0
) -> PublicRegistryDiscovery:
    """Create an adapter backed by a TestClient transport."""
    transport = httpx.MockTransport(lambda req: _forward_to_testclient(tc, req))
    disc = PublicRegistryDiscovery(
        "http://testregistry",
        heartbeat_interval=heartbeat_interval,
        identity=identity,
    )
    disc._http = httpx.AsyncClient(transport=transport)
    return disc


# ── Fixtures ───────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_rate_limits() -> None:
    """Clear rate-limit state before every test."""
    _rate_limit.clear()


@pytest.fixture()
def registry_test_client(tmp_path: Path):  # type: ignore[misc]
    db = tmp_path / "adapter_test.db"
    app = create_registry_app(db_path=db, prune_interval=9999.0)
    with TestClient(app) as tc:
        yield tc


@pytest.fixture()
def adapter(registry_test_client: TestClient):  # type: ignore[misc]
    """Create adapter with identity 1 backed by TestClient transport."""
    disc = _make_adapter(registry_test_client, _IDENTITY_1)
    yield disc


@pytest.fixture()
def adapter_2(registry_test_client: TestClient):  # type: ignore[misc]
    """Create adapter with identity 2 backed by TestClient transport."""
    disc = _make_adapter(registry_test_client, _IDENTITY_2)
    yield disc


# ── Register + Search ─────────────────────────────────────


async def test_register_and_search(adapter: PublicRegistryDiscovery) -> None:
    await adapter.register(SAMPLE_CARD)
    results = await adapter.search("code review")
    assert len(results) >= 1
    assert any(r["name"] == "Code Review" for r in results)


async def test_register_and_list(
    adapter: PublicRegistryDiscovery, adapter_2: PublicRegistryDiscovery
) -> None:
    await adapter.register(SAMPLE_CARD)
    await adapter_2.register(SAMPLE_CARD_2)
    agents = await adapter.list_agents()
    assert len(agents) == 2


async def test_register_and_get_agent(adapter: PublicRegistryDiscovery) -> None:
    await adapter.register(SAMPLE_CARD)
    card = await adapter.get_agent(SAMPLE_CARD["aid"])
    assert card is not None
    assert card["name"] == "test-agent"


# ── Deregister ─────────────────────────────────────────────


async def test_deregister_removes_agent(adapter: PublicRegistryDiscovery) -> None:
    await adapter.register(SAMPLE_CARD)
    await adapter.deregister(SAMPLE_CARD["aid"])
    card = await adapter.get_agent(SAMPLE_CARD["aid"])
    assert card is None


# ── Search edge cases ─────────────────────────────────────


async def test_search_returns_empty_for_no_match(adapter: PublicRegistryDiscovery) -> None:
    await adapter.register(SAMPLE_CARD)
    results = await adapter.search("blockchain")
    assert results == []


async def test_search_respects_max_price(
    adapter: PublicRegistryDiscovery, adapter_2: PublicRegistryDiscovery
) -> None:
    await adapter.register(SAMPLE_CARD)      # price=50
    await adapter_2.register(SAMPLE_CARD_2)  # price=30
    results = await adapter.search("review translation", max_price=40)
    for r in results:
        assert r["price"] <= 40


# ── Get agent not found ───────────────────────────────────


async def test_get_agent_not_found(adapter: PublicRegistryDiscovery) -> None:
    card = await adapter.get_agent("aid:nonexistent")
    assert card is None


# ── Heartbeat task ─────────────────────────────────────────


async def test_register_starts_heartbeat_task(adapter: PublicRegistryDiscovery) -> None:
    await adapter.register(SAMPLE_CARD)
    assert adapter._heartbeat_task is not None
    assert not adapter._heartbeat_task.done()
    await adapter.stop()


async def test_stop_cancels_heartbeat(adapter: PublicRegistryDiscovery) -> None:
    await adapter.register(SAMPLE_CARD)
    await adapter.stop()
    assert adapter._heartbeat_task is None


# ── Heartbeat re-registration on 404 ──────────────────────


async def test_heartbeat_reregisters_on_404(
    registry_test_client: TestClient,
) -> None:
    """When heartbeat gets 404 (registry wiped), adapter re-registers automatically."""
    disc = _make_adapter(registry_test_client, _IDENTITY_1, heartbeat_interval=0.1)
    try:
        await disc.register(SAMPLE_CARD)

        # Verify agent exists
        assert await disc.get_agent(SAMPLE_CARD["aid"]) is not None

        # Wipe the agent from registry (simulating a redeploy with ephemeral storage)
        store = registry_test_client.app.state.store
        await store.deregister_agent(SAMPLE_CARD["aid"])

        # Verify agent is gone
        assert await disc.get_agent(SAMPLE_CARD["aid"]) is None

        # Wait for heartbeat to fire and trigger re-registration (interval=0.1s)
        await asyncio.sleep(0.5)

        # Verify agent was re-registered automatically
        assert await disc.get_agent(SAMPLE_CARD["aid"]) is not None
    finally:
        await disc.stop()


# ── Agent card storage ────────────────────────────────────


async def test_register_stores_agent_card(adapter: PublicRegistryDiscovery) -> None:
    """After register(), agent_card is stored for potential re-registration."""
    await adapter.register(SAMPLE_CARD)
    assert adapter._agent_card is not None
    assert adapter._agent_card["name"] == "test-agent"
    await adapter.stop()
