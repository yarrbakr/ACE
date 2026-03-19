"""Gossip protocol data models — wire format for peer-to-peer discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class PeerInfo(BaseModel):
    """Information about a known peer in the gossip network."""

    aid: str
    url: str
    public_key_b64: str
    agent_card: dict[str, Any] = Field(default_factory=dict)
    last_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = 0


class GossipMessage(BaseModel):
    """Message exchanged between peers during gossip rounds."""

    sender_aid: str
    peers: list[PeerInfo]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    signature: str = ""


class GossipConfig(BaseModel):
    """Gossip-specific configuration parameters."""

    seed_peers: list[str] = Field(default_factory=list)
    gossip_interval: float = 30.0
    peer_timeout: float = 120.0
    max_peers: int = 100
    fanout: int = 3


# Request/response models for gossip HTTP endpoints


class AnnounceRequest(BaseModel):
    """A peer announcing itself to the network."""

    peer: PeerInfo
    signature: str = ""


class LeaveRequest(BaseModel):
    """A peer leaving the network gracefully."""

    aid: str
    signature: str = ""


__all__ = [
    "AnnounceRequest",
    "GossipConfig",
    "GossipMessage",
    "LeaveRequest",
    "PeerInfo",
]
