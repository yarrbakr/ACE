"""Gossip protocol discovery — peer-to-peer agent discovery via periodic exchange."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import random
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from ace.discovery.base import DiscoveryAdapter
from ace.discovery.gossip_models import GossipConfig, GossipMessage, PeerInfo
from ace.discovery.peer_manager import PeerManager

if TYPE_CHECKING:
    from ace.core.config import AceSettings
    from ace.core.identity import AgentIdentity

logger = logging.getLogger(__name__)


class GossipDiscovery(DiscoveryAdapter):
    """Adapter: gossip-based decentralized agent discovery."""

    def __init__(
        self,
        identity: AgentIdentity,
        settings: AceSettings,
        gossip_config: GossipConfig | None = None,
    ) -> None:
        self._identity = identity
        self._settings = settings
        self._config = gossip_config or GossipConfig(
            seed_peers=settings.seed_peers,
            gossip_interval=settings.gossip_interval,
            fanout=settings.gossip_fanout,
        )
        self._peer_manager = PeerManager(
            max_peers=self._config.max_peers,
            peer_timeout=self._config.peer_timeout,
        )
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        )
        self._gossip_task: asyncio.Task[None] | None = None
        self._own_version = 0

    @property
    def peer_manager(self) -> PeerManager:
        """Expose peer_manager for API route access."""
        return self._peer_manager

    def _own_peer_info(self) -> PeerInfo:
        """Build PeerInfo for the local agent."""
        url = f"http://127.0.0.1:{self._settings.port}"
        return PeerInfo(
            aid=self._identity.aid,
            url=url,
            public_key_b64=self._identity.public_key_b64,
            agent_card=self._peer_manager.get_peer(self._identity.aid).agent_card
            if self._peer_manager.get_peer(self._identity.aid)
            else {},
            last_seen=datetime.now(UTC),
            version=self._own_version,
        )

    # ── Lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        """Register self, contact seeds, and start the gossip loop."""
        self._peer_manager.add_peer(self._own_peer_info())
        await self._contact_seed_peers(self._config.seed_peers)
        self._gossip_task = asyncio.create_task(self._run_gossip_loop())
        logger.info(
            "Gossip discovery started (seeds=%d, interval=%.0fs, fanout=%d)",
            len(self._config.seed_peers),
            self._config.gossip_interval,
            self._config.fanout,
        )

    async def stop(self) -> None:
        """Cancel background loop and close HTTP client."""
        if self._gossip_task is not None:
            self._gossip_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._gossip_task
            self._gossip_task = None
        await self._http.aclose()
        logger.info("Gossip discovery stopped")

    # ── DiscoveryAdapter interface ─────────────────────────────

    async def register(self, agent_card: dict[str, Any]) -> None:
        self._own_version += 1
        own = self._own_peer_info()
        own.agent_card = agent_card
        own.version = self._own_version
        self._peer_manager.add_peer(own)
        # Announce to known peers
        await self._announce_to_peers(own)

    async def deregister(self, aid: str) -> None:
        self._peer_manager.remove_peer(aid)
        await self._send_leave_to_peers(aid)

    async def search(
        self, query: str, *, max_price: int | None = None
    ) -> list[dict[str, Any]]:
        peers = self._peer_manager.search_peers(query, max_price=max_price)
        return [p.agent_card for p in peers if p.agent_card]

    async def get_agent(self, aid: str) -> dict[str, Any] | None:
        peer = self._peer_manager.get_peer(aid)
        return peer.agent_card if peer else None

    async def list_agents(self) -> list[dict[str, Any]]:
        return [p.agent_card for p in self._peer_manager.get_all_peers() if p.agent_card]

    # ── Gossip protocol internals ──────────────────────────────

    async def _run_gossip_loop(self) -> None:
        """Periodic gossip: prune stale, exchange with random peers."""
        try:
            while True:
                self._peer_manager.prune_stale_peers()
                candidates = [
                    p for p in self._peer_manager.get_all_peers()
                    if p.aid != self._identity.aid
                ]
                selected = random.sample(
                    candidates, min(self._config.fanout, len(candidates))
                )
                for peer in selected:
                    await self._exchange_with_peer(peer)
                await asyncio.sleep(self._config.gossip_interval)
        except asyncio.CancelledError:
            return

    async def _exchange_with_peer(self, peer: PeerInfo) -> None:
        """Exchange peer lists with a single peer."""
        try:
            my_peers = self._peer_manager.get_all_peers()
            payload = {
                "sender_aid": self._identity.aid,
                "peers": [p.model_dump(mode="json") for p in my_peers],
                "timestamp": datetime.now(UTC).isoformat(),
            }
            signature = self._sign_payload(payload)
            message = GossipMessage(
                sender_aid=self._identity.aid,
                peers=my_peers,
                signature=signature,
            )
            resp = await self._http.post(
                f"{peer.url}/gossip/exchange",
                content=message.model_dump_json(),
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                resp_msg = GossipMessage(**data)
                if self._verify_message(resp_msg):
                    self._peer_manager.merge_peer_list(resp_msg.peers)
                # Update last_seen for this peer
                peer.last_seen = datetime.now(UTC)
                self._peer_manager.add_peer(peer)
        except httpx.ConnectError:
            logger.debug("Peer unreachable: %s", peer.url)
        except Exception:
            logger.debug("Gossip exchange failed with %s", peer.url, exc_info=True)

    async def _contact_seed_peers(self, seed_urls: list[str]) -> None:
        """Bootstrap by fetching peer lists from seed URLs."""
        for url in seed_urls:
            try:
                resp = await self._http.get(f"{url}/gossip/peers")
                if resp.status_code == 200:
                    data = resp.json()
                    peers = [PeerInfo(**p) for p in data.get("peers", [])]
                    self._peer_manager.merge_peer_list(peers)
                    logger.info("Bootstrapped %d peers from %s", len(peers), url)
            except httpx.ConnectError:
                logger.warning("Seed peer unreachable: %s", url)
            except Exception:
                logger.warning("Failed to contact seed %s", url, exc_info=True)

    async def _announce_to_peers(self, own: PeerInfo) -> None:
        """Announce self to all known peers."""
        payload = own.model_dump(mode="json")
        sig = self._sign_payload(payload)
        for peer in self._peer_manager.get_all_peers():
            if peer.aid == self._identity.aid:
                continue
            try:
                await self._http.post(
                    f"{peer.url}/gossip/announce",
                    json={"peer": payload, "signature": sig},
                )
            except Exception:
                logger.debug("Announce to %s failed", peer.url)

    async def _send_leave_to_peers(self, aid: str) -> None:
        """Notify peers that this agent is leaving."""
        payload = {"aid": aid}
        sig = self._sign_payload(payload)
        for peer in self._peer_manager.get_all_peers():
            if peer.aid == aid:
                continue
            try:
                await self._http.post(
                    f"{peer.url}/gossip/leave",
                    json={"aid": aid, "signature": sig},
                )
            except Exception:
                logger.debug("Leave notice to %s failed", peer.url)

    # ── Crypto helpers ─────────────────────────────────────────

    def _sign_payload(self, payload: dict[str, Any]) -> str:
        """Sign a JSON payload with our Ed25519 key."""
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        sig = self._identity.sign(canonical.encode("utf-8"))
        return base64.b64encode(sig).decode("ascii")

    def _verify_message(self, message: GossipMessage) -> bool:
        """Verify the signature on a gossip message."""
        sender = self._peer_manager.get_peer(message.sender_aid)
        if sender is None:
            return False
        try:
            payload = {
                "sender_aid": message.sender_aid,
                "peers": [p.model_dump(mode="json") for p in message.peers],
                "timestamp": message.timestamp.isoformat(),
            }
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            sig_bytes = base64.b64decode(message.signature)
            pub_bytes = base64.b64decode(sender.public_key_b64)
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )
            pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
            pub_key.verify(sig_bytes, canonical.encode("utf-8"))
            return True
        except Exception:
            logger.debug("Signature verification failed for %s", message.sender_aid)
            return False

    def verify_peer_signature(self, peer: PeerInfo, signature: str) -> bool:
        """Verify a signature made by a specific peer's key."""
        try:
            payload = peer.model_dump(mode="json")
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            sig_bytes = base64.b64decode(signature)
            pub_bytes = base64.b64decode(peer.public_key_b64)
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )
            pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
            pub_key.verify(sig_bytes, canonical.encode("utf-8"))
            return True
        except Exception:
            return False

    def verify_aid_signature(self, aid: str, data: dict[str, Any], signature: str) -> bool:
        """Verify a signature using a known peer's public key."""
        peer = self._peer_manager.get_peer(aid)
        if peer is None:
            # Also check if it matches local identity
            if aid == self._identity.aid:
                try:
                    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
                    sig_bytes = base64.b64decode(signature)
                    return self._identity.verify(canonical.encode("utf-8"), sig_bytes)
                except Exception:
                    return False
            return False
        try:
            canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
            sig_bytes = base64.b64decode(signature)
            pub_bytes = base64.b64decode(peer.public_key_b64)
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )
            pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
            pub_key.verify(sig_bytes, canonical.encode("utf-8"))
            return True
        except Exception:
            return False


__all__ = ["GossipDiscovery"]
