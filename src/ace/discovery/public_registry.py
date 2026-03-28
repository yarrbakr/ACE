"""Public registry discovery adapter — HTTP client for the ACE global registry.

Implements the ``DiscoveryAdapter`` ABC by talking to a remote (or local)
ACE registry service over HTTP.  Includes an automatic heartbeat loop
that keeps the agent's registration alive.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

from ace.discovery.base import DiscoveryAdapter

if TYPE_CHECKING:
    from ace.core.identity import AgentIdentity

logger = logging.getLogger(__name__)


class PublicRegistryDiscovery(DiscoveryAdapter):
    """Discovers agents via a public registry over HTTP."""

    def __init__(
        self,
        registry_url: str,
        *,
        heartbeat_interval: float = 60.0,
        identity: AgentIdentity | None = None,
    ) -> None:
        self._registry_url = registry_url.rstrip("/")
        self._heartbeat_interval = heartbeat_interval
        self._identity = identity
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        )
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._registered_aid: str | None = None
        self._agent_card: dict[str, Any] | None = None

    # ── Signed POST helper ─────────────────────────────────────

    async def _signed_post(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        """POST JSON with Ed25519 signature headers when identity is available."""
        body_bytes = json.dumps(payload, separators=(",", ":")).encode()
        headers: dict[str, str] = {}
        if self._identity is not None:
            sig = self._identity.sign(body_bytes)
            headers["X-Agent-ID"] = self._identity.aid
            headers["X-Signature"] = base64.b64encode(sig).decode()
        return await self._http.post(
            url,
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                **headers,
            },
        )

    # ── DiscoveryAdapter interface ─────────────────────────────

    async def register(self, agent_card: dict[str, Any]) -> None:
        """Register with the public registry and start heartbeat loop."""
        aid = agent_card.get("aid", "")
        self._agent_card = agent_card
        resp = await self._signed_post(
            f"{self._registry_url}/register",
            {"aid": aid, "agent_card": agent_card},
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
            await self._signed_post(
                f"{self._registry_url}/deregister",
                {"aid": aid},
            )
        except Exception:
            logger.debug("Deregister from registry failed", exc_info=True)
        self._registered_aid = None

    async def search(self, query: str, *, max_price: int | None = None) -> list[dict[str, Any]]:
        """Search the registry for capabilities."""
        params: dict[str, Any] = {"q": query}
        if max_price is not None:
            params["max_price"] = max_price
        resp = await self._http.get(f"{self._registry_url}/search", params=params)
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
        """Send periodic heartbeats to the registry.

        If the registry returns 404 (e.g. after a redeploy with ephemeral
        storage), automatically re-register with the stored agent card.
        """
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval)
                if self._registered_aid:
                    try:
                        resp = await self._signed_post(
                            f"{self._registry_url}/heartbeat",
                            {"aid": self._registered_aid},
                        )
                        if resp.status_code == 404 and self._agent_card is not None:
                            logger.info("Registry returned 404 on heartbeat, re-registering...")
                            await self.register(self._agent_card)
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
