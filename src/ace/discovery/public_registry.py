"""Public registry discovery adapter — HTTP client for the ACE global registry.

Implements the ``DiscoveryAdapter`` ABC by talking to a remote (or local)
ACE registry service over HTTP.  Includes an automatic heartbeat loop
that keeps the agent's registration alive.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import httpx

from ace.discovery.base import DiscoveryAdapter

logger = logging.getLogger(__name__)


class PublicRegistryDiscovery(DiscoveryAdapter):
    """Discovers agents via a public registry over HTTP."""

    def __init__(
        self,
        registry_url: str,
        *,
        heartbeat_interval: float = 60.0,
    ) -> None:
        self._registry_url = registry_url.rstrip("/")
        self._heartbeat_interval = heartbeat_interval
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        )
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._registered_aid: str | None = None

    # ── DiscoveryAdapter interface ─────────────────────────────

    async def register(self, agent_card: dict[str, Any]) -> None:
        """Register with the public registry and start heartbeat loop."""
        aid = agent_card.get("aid", "")
        resp = await self._http.post(
            f"{self._registry_url}/register",
            json={"aid": aid, "agent_card": agent_card},
        )
        resp.raise_for_status()
        self._registered_aid = aid
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("Registered with public registry at %s", self._registry_url)

    async def deregister(self, aid: str) -> None:
        """Deregister from the public registry and stop heartbeat."""
        await self._stop_heartbeat()
        try:
            await self._http.post(
                f"{self._registry_url}/deregister",
                json={"aid": aid},
            )
        except Exception:
            logger.debug("Deregister from registry failed", exc_info=True)
        self._registered_aid = None

    async def search(
        self, query: str, *, max_price: int | None = None
    ) -> list[dict[str, Any]]:
        """Search the registry for capabilities."""
        params: dict[str, Any] = {"q": query}
        if max_price is not None:
            params["max_price"] = max_price
        resp = await self._http.get(
            f"{self._registry_url}/search", params=params
        )
        resp.raise_for_status()
        return resp.json().get("results", [])  # type: ignore[no-any-return]

    async def get_agent(self, aid: str) -> dict[str, Any] | None:
        """Look up an agent card from the registry."""
        resp = await self._http.get(f"{self._registry_url}/agents/{aid}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("agent")  # type: ignore[no-any-return]

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all agents from the registry."""
        resp = await self._http.get(f"{self._registry_url}/agents")
        resp.raise_for_status()
        return resp.json().get("agents", [])  # type: ignore[no-any-return]

    # ── Lifecycle ──────────────────────────────────────────────

    async def stop(self) -> None:
        """Stop heartbeat and close HTTP client."""
        await self._stop_heartbeat()
        await self._http.aclose()

    # ── Heartbeat internals ────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to the registry."""
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval)
                if self._registered_aid:
                    try:
                        await self._http.post(
                            f"{self._registry_url}/heartbeat",
                            json={"aid": self._registered_aid},
                        )
                    except Exception:
                        logger.debug("Heartbeat failed", exc_info=True)
        except asyncio.CancelledError:
            return

    async def _stop_heartbeat(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None


__all__ = ["PublicRegistryDiscovery"]
