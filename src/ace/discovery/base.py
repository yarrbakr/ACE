"""Abstract discovery adapter interface — port/adapter pattern.

Implementations provide concrete agent-discovery mechanisms. The core
never depends on a specific discovery strategy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DiscoveryAdapter(ABC):
    """Port: pluggable agent discovery mechanism."""

    @abstractmethod
    async def register(self, agent_card: dict[str, Any]) -> None:
        """Announce this agent's capabilities to the network."""

    @abstractmethod
    async def deregister(self, aid: str) -> None:
        """Remove this agent from the network."""

    @abstractmethod
    async def search(self, query: str, *, max_price: int | None = None) -> list[dict[str, Any]]:
        """Search for capabilities matching a query."""

    @abstractmethod
    async def get_agent(self, aid: str) -> dict[str, Any] | None:
        """Retrieve an agent card by AID."""

    @abstractmethod
    async def list_agents(self) -> list[dict[str, Any]]:
        """List all known agents."""


__all__ = ["DiscoveryAdapter"]
