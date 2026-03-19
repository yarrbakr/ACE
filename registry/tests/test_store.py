"""Unit tests for the RegistryStore."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from registry.store import RegistryStore
from registry.tests.conftest import SAMPLE_AGENT_CARD, SAMPLE_AGENT_CARD_2


@pytest.fixture()
async def store(tmp_path: Path) -> RegistryStore:
    s = RegistryStore(tmp_path / "test.db")
    await s.initialize()
    return s


# ── Initialization ─────────────────────────────────────────


async def test_initialize_creates_tables(store: RegistryStore) -> None:
    """Store initializes without error and is ready."""
    count = await store.agent_count()
    assert count == 0


# ── Registration ───────────────────────────────────────────


async def test_register_agent(store: RegistryStore) -> None:
    await store.register_agent("aid:abc", SAMPLE_AGENT_CARD)
    assert await store.agent_count() == 1


async def test_register_agent_upserts(store: RegistryStore) -> None:
    """Re-registering the same AID updates rather than duplicating."""
    await store.register_agent("aid:abc", SAMPLE_AGENT_CARD)
    updated_card = {**SAMPLE_AGENT_CARD, "name": "updated-agent"}
    await store.register_agent("aid:abc", updated_card)
    assert await store.agent_count() == 1
    card = await store.get_agent("aid:abc")
    assert card is not None
    assert card["name"] == "updated-agent"


async def test_register_multiple_agents(store: RegistryStore) -> None:
    await store.register_agent("aid:a", SAMPLE_AGENT_CARD)
    await store.register_agent("aid:b", SAMPLE_AGENT_CARD_2)
    assert await store.agent_count() == 2


# ── Deregistration ─────────────────────────────────────────


async def test_deregister_agent(store: RegistryStore) -> None:
    await store.register_agent("aid:abc", SAMPLE_AGENT_CARD)
    result = await store.deregister_agent("aid:abc")
    assert result is True
    assert await store.agent_count() == 0


async def test_deregister_nonexistent(store: RegistryStore) -> None:
    result = await store.deregister_agent("aid:doesnotexist")
    assert result is False


# ── Heartbeat ──────────────────────────────────────────────


async def test_heartbeat_updates_timestamp(store: RegistryStore) -> None:
    await store.register_agent("aid:abc", SAMPLE_AGENT_CARD)
    found = await store.heartbeat("aid:abc")
    assert found is True


async def test_heartbeat_nonexistent(store: RegistryStore) -> None:
    found = await store.heartbeat("aid:missing")
    assert found is False


# ── Get Agent ──────────────────────────────────────────────


async def test_get_agent(store: RegistryStore) -> None:
    await store.register_agent("aid:abc", SAMPLE_AGENT_CARD)
    card = await store.get_agent("aid:abc")
    assert card is not None
    assert card["name"] == "test-agent"


async def test_get_agent_not_found(store: RegistryStore) -> None:
    card = await store.get_agent("aid:nope")
    assert card is None


# ── Search ─────────────────────────────────────────────────


async def test_search_by_name(store: RegistryStore) -> None:
    await store.register_agent("aid:abc", SAMPLE_AGENT_CARD)
    results = await store.search("code review")
    assert len(results) >= 1
    assert results[0]["name"] == "Code Review"


async def test_search_by_description(store: RegistryStore) -> None:
    await store.register_agent("aid:abc", SAMPLE_AGENT_CARD)
    results = await store.search("python")
    assert len(results) >= 1


async def test_search_by_tags(store: RegistryStore) -> None:
    await store.register_agent("aid:abc", SAMPLE_AGENT_CARD)
    results = await store.search("review")
    assert len(results) >= 1


async def test_search_max_price_filter(store: RegistryStore) -> None:
    await store.register_agent("aid:a", SAMPLE_AGENT_CARD)
    await store.register_agent("aid:b", SAMPLE_AGENT_CARD_2)
    # SAMPLE_AGENT_CARD has price=50, SAMPLE_AGENT_CARD_2 has 30 and 100
    results = await store.search("review python translation nlp", max_price=40)
    prices = [r["price"] for r in results]
    assert all(p <= 40 for p in prices)


async def test_search_empty_query(store: RegistryStore) -> None:
    results = await store.search("")
    assert results == []


async def test_search_no_match(store: RegistryStore) -> None:
    await store.register_agent("aid:abc", SAMPLE_AGENT_CARD)
    results = await store.search("blockchain")
    assert results == []


# ── List Agents ────────────────────────────────────────────


async def test_list_agents(store: RegistryStore) -> None:
    await store.register_agent("aid:a", SAMPLE_AGENT_CARD)
    await store.register_agent("aid:b", SAMPLE_AGENT_CARD_2)
    agents = await store.list_agents()
    assert len(agents) == 2


# ── Prune ──────────────────────────────────────────────────


async def test_prune_stale_agents(store: RegistryStore) -> None:
    """Agents with old heartbeats get pruned."""
    await store.register_agent("aid:stale", SAMPLE_AGENT_CARD)
    # Manually backdate the heartbeat
    import aiosqlite

    async with aiosqlite.connect(store._db_path) as db:
        await db.execute(
            "UPDATE registered_agents SET last_heartbeat = datetime('now', '-600 seconds') WHERE aid = ?",
            ("aid:stale",),
        )
        await db.commit()
    pruned = await store.prune_stale(max_age_seconds=300)
    assert "aid:stale" in pruned
    assert await store.agent_count() == 0


async def test_prune_keeps_fresh_agents(store: RegistryStore) -> None:
    """Fresh agents survive pruning."""
    await store.register_agent("aid:fresh", SAMPLE_AGENT_CARD)
    pruned = await store.prune_stale(max_age_seconds=300)
    assert pruned == []
    assert await store.agent_count() == 1
