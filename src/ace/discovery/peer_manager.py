"""Peer state management — pure in-memory store, no I/O."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ace.discovery.gossip_models import PeerInfo


class PeerManager:
    """Manages the set of known peers. No networking, no async — pure state."""

    def __init__(self, max_peers: int = 100, peer_timeout: float = 120.0) -> None:
        self._peers: dict[str, PeerInfo] = {}
        self._max_peers = max_peers
        self._peer_timeout = peer_timeout

    @property
    def peer_count(self) -> int:
        return len(self._peers)

    def add_peer(self, peer: PeerInfo) -> bool:
        """Add or update a peer. Returns True if state changed."""
        existing = self._peers.get(peer.aid)
        if existing is not None:
            if peer.version > existing.version:
                self._peers[peer.aid] = peer
                return True
            return False
        if len(self._peers) >= self._max_peers:
            return False
        self._peers[peer.aid] = peer
        return True

    def remove_peer(self, aid: str) -> bool:
        """Remove a peer by AID. Returns True if it existed."""
        return self._peers.pop(aid, None) is not None

    def get_peer(self, aid: str) -> PeerInfo | None:
        return self._peers.get(aid)

    def get_all_peers(self) -> list[PeerInfo]:
        return list(self._peers.values())

    def merge_peer_list(self, peers: list[PeerInfo]) -> int:
        """Merge incoming peers. Returns count of adds/updates."""
        changed = 0
        for peer in peers:
            if self.add_peer(peer):
                changed += 1
        return changed

    def prune_stale_peers(self, *, now: datetime | None = None) -> list[str]:
        """Remove peers older than peer_timeout. Returns pruned AIDs."""
        if now is None:
            now = datetime.now(UTC)
        pruned: list[str] = []
        for aid, peer in list(self._peers.items()):
            age = (now - peer.last_seen).total_seconds()
            if age > self._peer_timeout:
                del self._peers[aid]
                pruned.append(aid)
        return pruned

    def search_peers(
        self, query: str, max_price: int | None = None
    ) -> list[PeerInfo]:
        """Search peers by keyword in agent_card (name, description, tags)."""
        words = query.lower().split()
        if not words:
            return []

        results: list[PeerInfo] = []
        for peer in self._peers.values():
            card = peer.agent_card
            if not card:
                continue
            searchable = " ".join([
                card.get("name", ""),
                card.get("description", ""),
            ]).lower()

            # Also search capabilities
            for cap in card.get("capabilities", []):
                searchable += " " + cap.get("name", "").lower()
                searchable += " " + cap.get("description", "").lower()
                searchable += " " + " ".join(cap.get("tags", [])).lower()

            if not any(w in searchable for w in words):
                continue

            # Apply max_price filter
            if max_price is not None:
                has_affordable = False
                for cap in card.get("capabilities", []):
                    price = cap.get("pricing", {}).get("amount", 0)
                    if price <= max_price:
                        has_affordable = True
                        break
                if not has_affordable:
                    continue

            results.append(peer)
        return results


__all__ = ["PeerManager"]
