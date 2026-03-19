"""Centralized registry client — delegates to CapabilityRegistry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ace.core.capability import CapabilityRegistry
from ace.discovery.base import DiscoveryAdapter


class CentralizedDiscovery(DiscoveryAdapter):
    """Adapter: centralized registry for agent discovery."""

    def __init__(self, registry_url: str, db_path: Path) -> None:
        self.registry_url = registry_url
        self._registry = CapabilityRegistry(db_path)
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self._registry.initialize()
            self._initialized = True

    async def register(self, agent_card: dict[str, Any]) -> None:
        await self._ensure_initialized()
        aid = agent_card.get("aid", "")
        await self._registry.register(aid, agent_card)

    async def deregister(self, aid: str) -> None:
        await self._ensure_initialized()
        await self._registry.unregister(aid)

    async def search(self, query: str, *, max_price: int | None = None) -> list[dict[str, Any]]:
        await self._ensure_initialized()
        return await self._registry.search(query, max_price=max_price)

    async def get_agent(self, aid: str) -> dict[str, Any] | None:
        await self._ensure_initialized()
        return await self._registry.get_agent_card(aid)

    async def list_agents(self) -> list[dict[str, Any]]:
        await self._ensure_initialized()
        return await self._registry.list_all()


__all__ = ["CentralizedDiscovery"]
