"""Integration tests for PublicRegistryDiscovery adapter against a real registry."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from ace.discovery.public_registry import PublicRegistryDiscovery
from registry.app import create_registry_app

SAMPLE_CARD: dict[str, Any] = {
    "name": "test-agent",
    "description": "An agent for adapter tests",
    "url": "http://localhost:8080",
    "capabilities": [
        {
            "id": "code_review",
            "name": "Code Review",
            "description": "Reviews Python code for quality",
            "pricing": {"currency": "AGC", "model": "per_call", "amount": 50},
            "tags": ["python", "review"],
        }
    ],
    "authentication": {"type": "ed25519", "public_key": "dGVzdGtleQ=="},
    "aid": "aid:adaptertest",
}

SAMPLE_CARD_2: dict[str, Any] = {
    "name": "translator-agent",
    "description": "Translates text",
    "url": "http://localhost:8081",
    "capabilities": [
        {
            "id": "translate",
            "name": "Translation",
            "description": "Translates text between languages",
            "pricing": {"currency": "AGC", "model": "per_call", "amount": 30},
            "tags": ["translation", "nlp"],
        }
    ],
    "authentication": {"type": "ed25519", "public_key": "c2Vjb25ka2V5"},
    "aid": "aid:translatortest",
}


@pytest.fixture()
def registry_test_client(tmp_path: Path):  # type: ignore[misc]
    db = tmp_path / "adapter_test.db"
    app = create_registry_app(db_path=db, prune_interval=9999.0)
    with TestClient(app) as tc:
        yield tc


@pytest.fixture()
def adapter(registry_test_client: TestClient):  # type: ignore[misc]
    """Create adapter with httpx client backed by TestClient transport."""
    transport = httpx.MockTransport(
        lambda req: _forward_to_testclient(registry_test_client, req)
    )
    disc = PublicRegistryDiscovery(
        "http://testregistry",
        heartbeat_interval=9999.0,
    )
    disc._http = httpx.AsyncClient(transport=transport)
    yield disc


def _forward_to_testclient(
    tc: TestClient, request: httpx.Request
) -> httpx.Response:
    """Forward an httpx Request to a FastAPI TestClient."""
    url = str(request.url)
    path = url.replace("http://testregistry", "")
    body = request.content

    if request.method == "GET":
        resp = tc.get(path)
    elif request.method == "POST":
        resp = tc.post(path, content=body, headers={"content-type": "application/json"})
    else:
        resp = tc.request(request.method, path, content=body)

    return httpx.Response(
        status_code=resp.status_code,
        headers=dict(resp.headers),
        content=resp.content,
    )


# ── Register + Search ─────────────────────────────────────


async def test_register_and_search(adapter: PublicRegistryDiscovery) -> None:
    await adapter.register(SAMPLE_CARD)
    results = await adapter.search("code review")
    assert len(results) >= 1
    assert any(r["name"] == "Code Review" for r in results)


async def test_register_and_list(adapter: PublicRegistryDiscovery) -> None:
    await adapter.register(SAMPLE_CARD)
    await adapter.register(SAMPLE_CARD_2)
    agents = await adapter.list_agents()
    assert len(agents) == 2


async def test_register_and_get_agent(adapter: PublicRegistryDiscovery) -> None:
    await adapter.register(SAMPLE_CARD)
    card = await adapter.get_agent("aid:adaptertest")
    assert card is not None
    assert card["name"] == "test-agent"


# ── Deregister ─────────────────────────────────────────────


async def test_deregister_removes_agent(adapter: PublicRegistryDiscovery) -> None:
    await adapter.register(SAMPLE_CARD)
    await adapter.deregister("aid:adaptertest")
    card = await adapter.get_agent("aid:adaptertest")
    assert card is None


# ── Search edge cases ─────────────────────────────────────


async def test_search_returns_empty_for_no_match(adapter: PublicRegistryDiscovery) -> None:
    await adapter.register(SAMPLE_CARD)
    results = await adapter.search("blockchain")
    assert results == []


async def test_search_respects_max_price(adapter: PublicRegistryDiscovery) -> None:
    await adapter.register(SAMPLE_CARD)  # price=50
    await adapter.register(SAMPLE_CARD_2)  # price=30
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
