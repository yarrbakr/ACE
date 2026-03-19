"""Tests for gossip discovery protocol — PeerManager, GossipDiscovery, and API endpoints."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from ace.api.server import create_app
from ace.core.config import AceSettings, DiscoveryMode
from ace.core.identity import AgentIdentity
from ace.discovery.gossip import GossipDiscovery
from ace.discovery.gossip_models import (
    GossipConfig,
    GossipMessage,
    PeerInfo,
)
from ace.discovery.peer_manager import PeerManager


# ── Helpers ─────────────────────────────────────────────────


def _make_peer(
    aid: str = "aid:testpeer1",
    url: str = "http://127.0.0.1:9001",
    version: int = 1,
    agent_card: dict | None = None,
    last_seen: datetime | None = None,
    public_key_b64: str = "",
) -> PeerInfo:
    return PeerInfo(
        aid=aid,
        url=url,
        public_key_b64=public_key_b64,
        agent_card=agent_card or {},
        last_seen=last_seen or datetime.now(timezone.utc),
        version=version,
    )


def _make_peer_with_card(
    aid: str = "aid:testpeer1",
    name: str = "Test Agent",
    description: str = "A test agent",
    tags: list[str] | None = None,
    price: int = 50,
    version: int = 1,
) -> PeerInfo:
    return _make_peer(
        aid=aid,
        version=version,
        agent_card={
            "name": name,
            "description": description,
            "aid": aid,
            "capabilities": [
                {
                    "name": "test_skill",
                    "description": f"Skill from {name}",
                    "tags": tags or ["test"],
                    "pricing": {"currency": "AGC", "model": "per_call", "amount": price},
                }
            ],
        },
    )


# ═══════════════════════════════════════════════════════════
# PeerManager Unit Tests
# ═══════════════════════════════════════════════════════════


class TestPeerManagerAdd:
    def test_add_peer_stores_correctly(self) -> None:
        pm = PeerManager()
        peer = _make_peer()
        assert pm.add_peer(peer) is True
        assert pm.peer_count == 1
        assert pm.get_peer(peer.aid) == peer

    def test_add_peer_higher_version_updates(self) -> None:
        pm = PeerManager()
        old = _make_peer(version=1)
        new = _make_peer(version=2, url="http://127.0.0.1:9999")
        pm.add_peer(old)
        assert pm.add_peer(new) is True
        assert pm.get_peer(old.aid).url == "http://127.0.0.1:9999"

    def test_add_peer_lower_version_does_not_update(self) -> None:
        pm = PeerManager()
        new = _make_peer(version=5)
        old = _make_peer(version=3)
        pm.add_peer(new)
        assert pm.add_peer(old) is False
        assert pm.get_peer(new.aid).version == 5

    def test_add_peer_same_version_does_not_update(self) -> None:
        pm = PeerManager()
        p1 = _make_peer(version=2, url="http://first:8080")
        p2 = _make_peer(version=2, url="http://second:8080")
        pm.add_peer(p1)
        assert pm.add_peer(p2) is False
        assert pm.get_peer(p1.aid).url == "http://first:8080"

    def test_add_peer_respects_max_peers(self) -> None:
        pm = PeerManager(max_peers=2)
        pm.add_peer(_make_peer(aid="aid:a"))
        pm.add_peer(_make_peer(aid="aid:b"))
        assert pm.add_peer(_make_peer(aid="aid:c")) is False
        assert pm.peer_count == 2


class TestPeerManagerRemove:
    def test_remove_existing_returns_true(self) -> None:
        pm = PeerManager()
        pm.add_peer(_make_peer())
        assert pm.remove_peer("aid:testpeer1") is True
        assert pm.peer_count == 0

    def test_remove_unknown_returns_false(self) -> None:
        pm = PeerManager()
        assert pm.remove_peer("aid:nonexistent") is False


class TestPeerManagerGet:
    def test_get_known_returns_peer(self) -> None:
        pm = PeerManager()
        peer = _make_peer()
        pm.add_peer(peer)
        assert pm.get_peer("aid:testpeer1") is not None

    def test_get_unknown_returns_none(self) -> None:
        pm = PeerManager()
        assert pm.get_peer("aid:unknown") is None


class TestPeerManagerMerge:
    def test_merge_adds_new_peers(self) -> None:
        pm = PeerManager()
        peers = [_make_peer(aid="aid:a"), _make_peer(aid="aid:b")]
        assert pm.merge_peer_list(peers) == 2
        assert pm.peer_count == 2

    def test_merge_updates_higher_version(self) -> None:
        pm = PeerManager()
        pm.add_peer(_make_peer(aid="aid:a", version=1))
        changed = pm.merge_peer_list([_make_peer(aid="aid:a", version=3)])
        assert changed == 1
        assert pm.get_peer("aid:a").version == 3

    def test_merge_ignores_lower_version(self) -> None:
        pm = PeerManager()
        pm.add_peer(_make_peer(aid="aid:a", version=5))
        changed = pm.merge_peer_list([_make_peer(aid="aid:a", version=2)])
        assert changed == 0
        assert pm.get_peer("aid:a").version == 5

    def test_merge_returns_correct_count(self) -> None:
        pm = PeerManager()
        pm.add_peer(_make_peer(aid="aid:a", version=1))
        peers = [
            _make_peer(aid="aid:a", version=3),  # update
            _make_peer(aid="aid:b", version=1),  # new
            _make_peer(aid="aid:a", version=2),  # stale, ignored
        ]
        assert pm.merge_peer_list(peers) == 2


class TestPeerManagerPrune:
    def test_prune_removes_stale_peers(self) -> None:
        pm = PeerManager(peer_timeout=60.0)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        pm.add_peer(_make_peer(aid="aid:old", last_seen=old_time))
        pm.add_peer(_make_peer(aid="aid:new"))
        pruned = pm.prune_stale_peers()
        assert "aid:old" in pruned
        assert pm.peer_count == 1

    def test_prune_keeps_recent_peers(self) -> None:
        pm = PeerManager(peer_timeout=60.0)
        pm.add_peer(_make_peer(aid="aid:fresh"))
        pruned = pm.prune_stale_peers()
        assert pruned == []
        assert pm.peer_count == 1

    def test_prune_with_custom_now(self) -> None:
        pm = PeerManager(peer_timeout=60.0)
        t = datetime.now(timezone.utc)
        pm.add_peer(_make_peer(aid="aid:a", last_seen=t))
        future = t + timedelta(seconds=120)
        pruned = pm.prune_stale_peers(now=future)
        assert "aid:a" in pruned


class TestPeerManagerSearch:
    def test_search_by_name(self) -> None:
        pm = PeerManager()
        pm.add_peer(_make_peer_with_card(aid="aid:a", name="Python Coder"))
        pm.add_peer(_make_peer_with_card(aid="aid:b", name="Rust Builder"))
        results = pm.search_peers("python")
        assert len(results) == 1
        assert results[0].aid == "aid:a"

    def test_search_by_description(self) -> None:
        pm = PeerManager()
        pm.add_peer(_make_peer_with_card(aid="aid:a", description="Generates Python code"))
        results = pm.search_peers("generates")
        assert len(results) == 1

    def test_search_by_tag(self) -> None:
        pm = PeerManager()
        pm.add_peer(_make_peer_with_card(aid="aid:a", tags=["machine-learning", "ai"]))
        results = pm.search_peers("machine-learning")
        assert len(results) == 1

    def test_search_max_price_filter(self) -> None:
        pm = PeerManager()
        pm.add_peer(_make_peer_with_card(aid="aid:cheap", price=10))
        pm.add_peer(_make_peer_with_card(aid="aid:expensive", price=500))
        results = pm.search_peers("test", max_price=100)
        assert len(results) == 1
        assert results[0].aid == "aid:cheap"

    def test_search_no_matches(self) -> None:
        pm = PeerManager()
        pm.add_peer(_make_peer_with_card(aid="aid:a"))
        results = pm.search_peers("nonexistent_skill_xyz")
        assert results == []

    def test_search_empty_query(self) -> None:
        pm = PeerManager()
        pm.add_peer(_make_peer_with_card(aid="aid:a"))
        results = pm.search_peers("")
        assert results == []


# ═══════════════════════════════════════════════════════════
# GossipDiscovery Integration Tests
# ═══════════════════════════════════════════════════════════


@pytest.fixture()
def gossip_identity() -> AgentIdentity:
    return AgentIdentity()


@pytest.fixture()
def gossip_settings(tmp_path: Path) -> AceSettings:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return AceSettings(
        agent_name="gossip-test",
        port=9001,
        data_dir=data_dir,
        discovery_mode=DiscoveryMode.GOSSIP,
        seed_peers=[],
    )


@pytest.fixture()
def gossip_config() -> GossipConfig:
    return GossipConfig(
        seed_peers=[],
        gossip_interval=1.0,
        peer_timeout=10.0,
        max_peers=50,
        fanout=2,
    )


@pytest.fixture()
def gossip_discovery(
    gossip_identity: AgentIdentity,
    gossip_settings: AceSettings,
    gossip_config: GossipConfig,
) -> GossipDiscovery:
    return GossipDiscovery(gossip_identity, gossip_settings, gossip_config)


class TestGossipDiscoveryLifecycle:
    async def test_start_registers_self(
        self, gossip_discovery: GossipDiscovery, gossip_identity: AgentIdentity
    ) -> None:
        await gossip_discovery.start()
        try:
            own = gossip_discovery.peer_manager.get_peer(gossip_identity.aid)
            assert own is not None
            assert own.aid == gossip_identity.aid
        finally:
            await gossip_discovery.stop()

    async def test_start_with_unreachable_seeds_continues(
        self, gossip_identity: AgentIdentity, gossip_settings: AceSettings
    ) -> None:
        config = GossipConfig(seed_peers=["http://127.0.0.1:59999"], gossip_interval=1.0)
        gd = GossipDiscovery(gossip_identity, gossip_settings, config)
        await gd.start()
        try:
            # Should not crash, just log warning
            assert gd.peer_manager.peer_count >= 1  # self
        finally:
            await gd.stop()

    async def test_stop_cancels_task_and_closes_client(
        self, gossip_discovery: GossipDiscovery
    ) -> None:
        await gossip_discovery.start()
        assert gossip_discovery._gossip_task is not None
        await gossip_discovery.stop()
        assert gossip_discovery._gossip_task is None


class TestGossipDiscoveryAdapter:
    async def test_register_updates_own_card(
        self, gossip_discovery: GossipDiscovery, gossip_identity: AgentIdentity
    ) -> None:
        await gossip_discovery.start()
        try:
            card = {"name": "Test Agent", "aid": gossip_identity.aid, "capabilities": []}
            await gossip_discovery.register(card)
            own = gossip_discovery.peer_manager.get_peer(gossip_identity.aid)
            assert own is not None
            assert own.agent_card["name"] == "Test Agent"
            assert own.version >= 1
        finally:
            await gossip_discovery.stop()

    async def test_deregister_removes_peer(
        self, gossip_discovery: GossipDiscovery, gossip_identity: AgentIdentity
    ) -> None:
        await gossip_discovery.start()
        try:
            await gossip_discovery.deregister(gossip_identity.aid)
            assert gossip_discovery.peer_manager.get_peer(gossip_identity.aid) is None
        finally:
            await gossip_discovery.stop()

    async def test_search_finds_capabilities(
        self, gossip_discovery: GossipDiscovery
    ) -> None:
        await gossip_discovery.start()
        try:
            # Add a peer with capabilities
            peer = _make_peer_with_card(
                aid="aid:searchable",
                name="Python Code Gen",
                tags=["python", "codegen"],
            )
            gossip_discovery.peer_manager.add_peer(peer)
            results = await gossip_discovery.search("python")
            assert len(results) == 1
            assert results[0]["name"] == "Python Code Gen"
        finally:
            await gossip_discovery.stop()

    async def test_get_agent_returns_card(
        self, gossip_discovery: GossipDiscovery
    ) -> None:
        await gossip_discovery.start()
        try:
            peer = _make_peer_with_card(aid="aid:known")
            gossip_discovery.peer_manager.add_peer(peer)
            card = await gossip_discovery.get_agent("aid:known")
            assert card is not None
            assert card["aid"] == "aid:known"
        finally:
            await gossip_discovery.stop()

    async def test_get_agent_unknown_returns_none(
        self, gossip_discovery: GossipDiscovery
    ) -> None:
        await gossip_discovery.start()
        try:
            assert await gossip_discovery.get_agent("aid:unknown") is None
        finally:
            await gossip_discovery.stop()

    async def test_list_agents_returns_all(
        self, gossip_discovery: GossipDiscovery
    ) -> None:
        await gossip_discovery.start()
        try:
            gossip_discovery.peer_manager.add_peer(
                _make_peer_with_card(aid="aid:a")
            )
            gossip_discovery.peer_manager.add_peer(
                _make_peer_with_card(aid="aid:b")
            )
            agents = await gossip_discovery.list_agents()
            aids = {a["aid"] for a in agents}
            assert "aid:a" in aids
            assert "aid:b" in aids
        finally:
            await gossip_discovery.stop()


class TestGossipCrypto:
    def test_sign_and_verify_roundtrip(
        self, gossip_discovery: GossipDiscovery, gossip_identity: AgentIdentity
    ) -> None:
        payload = {"test": "data", "number": 42}
        sig = gossip_discovery._sign_payload(payload)
        # Verify manually
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        sig_bytes = base64.b64decode(sig)
        assert gossip_identity.verify(canonical.encode("utf-8"), sig_bytes)

    def test_verify_message_with_known_sender(
        self, gossip_discovery: GossipDiscovery, gossip_identity: AgentIdentity
    ) -> None:
        # Register self first so we're a known peer
        own = PeerInfo(
            aid=gossip_identity.aid,
            url="http://127.0.0.1:9001",
            public_key_b64=gossip_identity.public_key_b64,
            version=1,
        )
        gossip_discovery.peer_manager.add_peer(own)

        # Build a properly signed message
        peers = [own]
        ts = datetime.now(timezone.utc)
        payload = {
            "sender_aid": gossip_identity.aid,
            "peers": [p.model_dump(mode="json") for p in peers],
            "timestamp": ts.isoformat(),
        }
        sig = gossip_discovery._sign_payload(payload)
        msg = GossipMessage(
            sender_aid=gossip_identity.aid,
            peers=peers,
            timestamp=ts,
            signature=sig,
        )
        assert gossip_discovery._verify_message(msg) is True

    def test_verify_message_invalid_sig_returns_false(
        self, gossip_discovery: GossipDiscovery, gossip_identity: AgentIdentity
    ) -> None:
        own = PeerInfo(
            aid=gossip_identity.aid,
            url="http://127.0.0.1:9001",
            public_key_b64=gossip_identity.public_key_b64,
            version=1,
        )
        gossip_discovery.peer_manager.add_peer(own)
        msg = GossipMessage(
            sender_aid=gossip_identity.aid,
            peers=[own],
            signature="badsignature==",
        )
        assert gossip_discovery._verify_message(msg) is False

    def test_verify_message_unknown_sender_returns_false(
        self, gossip_discovery: GossipDiscovery
    ) -> None:
        msg = GossipMessage(
            sender_aid="aid:unknown",
            peers=[],
            signature="anything",
        )
        assert gossip_discovery._verify_message(msg) is False


class TestGossipSelfLoop:
    async def test_gossip_loop_skips_self(
        self, gossip_discovery: GossipDiscovery, gossip_identity: AgentIdentity
    ) -> None:
        """The gossip loop should never exchange with itself."""
        await gossip_discovery.start()
        try:
            candidates = [
                p for p in gossip_discovery.peer_manager.get_all_peers()
                if p.aid != gossip_identity.aid
            ]
            # With only self registered, no candidates to exchange with
            assert candidates == []
        finally:
            await gossip_discovery.stop()


# ═══════════════════════════════════════════════════════════
# Gossip API Endpoint Tests
# ═══════════════════════════════════════════════════════════


@pytest.fixture()
def gossip_app_settings(tmp_path: Path) -> AceSettings:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return AceSettings(
        agent_name="gossip-api-test",
        port=9001,
        data_dir=data_dir,
        discovery_mode=DiscoveryMode.GOSSIP,
        seed_peers=[],
        gossip_interval=999.0,  # very long so loop doesn't interfere
    )


@pytest.fixture()
def gossip_app_identity() -> AgentIdentity:
    return AgentIdentity()


@pytest.fixture()
def gossip_client(
    gossip_app_settings: AceSettings, gossip_app_identity: AgentIdentity
):
    app = create_app(settings=gossip_app_settings, identity=gossip_app_identity)
    with TestClient(app) as tc:
        yield tc, gossip_app_identity


def _sign_and_post_gossip(
    tc: TestClient,
    path: str,
    body: dict,
    identity: AgentIdentity,
):
    """POST with Ed25519 signature for gossip endpoints."""
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    sig = identity.sign(body_bytes)
    headers = {
        "X-Agent-ID": identity.aid,
        "X-Signature": base64.b64encode(sig).decode(),
        "Content-Type": "application/json",
    }
    return tc.post(path, content=body_bytes, headers=headers)


class TestGossipEndpointPeers:
    def test_get_peers_returns_list(self, gossip_client) -> None:
        tc, identity = gossip_client
        resp = tc.get("/gossip/peers")
        assert resp.status_code == 200
        data = resp.json()
        assert "peers" in data
        # Should at least have self
        assert len(data["peers"]) >= 1


class TestGossipEndpointAnnounce:
    def test_announce_with_valid_signature(self, gossip_client) -> None:
        tc, server_identity = gossip_client
        # Create a new identity that will announce itself
        new_agent = AgentIdentity()
        peer_info = PeerInfo(
            aid=new_agent.aid,
            url="http://127.0.0.1:9002",
            public_key_b64=new_agent.public_key_b64,
            agent_card={"name": "New Agent", "aid": new_agent.aid},
            version=1,
        )
        payload = peer_info.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        sig = base64.b64encode(new_agent.sign(canonical.encode())).decode()

        body = {"peer": payload, "signature": sig}
        resp = _sign_and_post_gossip(tc, "/gossip/announce", body, server_identity)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_announce_spoofing_rejected(self, gossip_client) -> None:
        tc, server_identity = gossip_client
        # Try to announce with a mismatched key
        victim = AgentIdentity()
        attacker = AgentIdentity()
        peer_info = PeerInfo(
            aid=victim.aid,  # victim's AID
            url="http://127.0.0.1:9999",
            public_key_b64=victim.public_key_b64,  # victim's key
            version=1,
        )
        payload = peer_info.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        # Sign with attacker's key (doesn't match victim's public_key_b64)
        sig = base64.b64encode(attacker.sign(canonical.encode())).decode()

        body = {"peer": payload, "signature": sig}
        resp = _sign_and_post_gossip(tc, "/gossip/announce", body, server_identity)
        assert resp.status_code == 403


class TestGossipEndpointLeave:
    def test_leave_with_valid_signature(self, gossip_client) -> None:
        tc, server_identity = gossip_client
        # First announce, then leave
        new_agent = AgentIdentity()
        peer_info = PeerInfo(
            aid=new_agent.aid,
            url="http://127.0.0.1:9002",
            public_key_b64=new_agent.public_key_b64,
            agent_card={},
            version=1,
        )
        # Add the peer so it can be found for signature verification
        payload = peer_info.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        sig = base64.b64encode(new_agent.sign(canonical.encode())).decode()
        _sign_and_post_gossip(
            tc, "/gossip/announce", {"peer": payload, "signature": sig}, server_identity
        )

        # Now leave
        leave_payload = {"aid": new_agent.aid}
        leave_canonical = json.dumps(leave_payload, sort_keys=True, separators=(",", ":"))
        leave_sig = base64.b64encode(new_agent.sign(leave_canonical.encode())).decode()
        resp = _sign_and_post_gossip(
            tc,
            "/gossip/leave",
            {"aid": new_agent.aid, "signature": leave_sig},
            server_identity,
        )
        assert resp.status_code == 200


class TestGossipEndpointNotInCentralized:
    def test_gossip_endpoints_not_mounted_in_centralized(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        settings = AceSettings(
            agent_name="central-test",
            port=8080,
            data_dir=data_dir,
            discovery_mode=DiscoveryMode.CENTRALIZED,
        )
        identity = AgentIdentity()
        app = create_app(settings=settings, identity=identity)
        with TestClient(app) as tc:
            resp = tc.get("/gossip/peers")
            assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════
# Status Endpoint with Gossip Info
# ═══════════════════════════════════════════════════════════


class TestStatusWithGossip:
    def test_status_shows_gossip_mode(self, gossip_client) -> None:
        tc, _ = gossip_client
        resp = tc.get("/admin/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["discovery_mode"] == "gossip"
        assert "known_peers" in data

    def test_status_shows_centralized_mode(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        settings = AceSettings(
            agent_name="central-test",
            port=8080,
            data_dir=data_dir,
            discovery_mode=DiscoveryMode.CENTRALIZED,
        )
        identity = AgentIdentity()
        app = create_app(settings=settings, identity=identity)
        with TestClient(app) as tc:
            resp = tc.get("/admin/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["discovery_mode"] == "centralized"
