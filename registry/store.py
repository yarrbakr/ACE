"""Registry data store — SQLite-backed agent registry with in-memory cache."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class RegistryStore:
    """SQLite-backed agent registry with in-memory cache.

    Follows the same patterns as ``ace.core.capability.CapabilityRegistry``:
    connection-per-operation, WAL mode, parameterised queries only.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._cache: dict[str, dict[str, Any]] = {}

    # ── Lifecycle ──────────────────────────────────────────────

    async def initialize(self) -> None:
        """Create tables and populate in-memory cache."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            schema = _SCHEMA_PATH.read_text(encoding="utf-8")
            await db.executescript(schema)
            await db.commit()
        await self._load_cache()

    async def _load_cache(self) -> None:
        """Populate in-memory cache from SQLite."""
        self._cache.clear()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("SELECT aid, agent_card FROM registered_agents")
            rows = await cursor.fetchall()
            for aid, card_json in rows:
                self._cache[aid] = json.loads(card_json)

    # ── Agent registration ─────────────────────────────────────

    async def register_agent(self, aid: str, agent_card: dict[str, Any]) -> None:
        """Register or update an agent card. Replaces existing capabilities."""
        card_json = json.dumps(agent_card)
        name = agent_card.get("name", "")
        description = agent_card.get("description", "")
        url = agent_card.get("url", "")

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            # Upsert agent
            await db.execute(
                """
                INSERT INTO registered_agents (aid, agent_card, name, description, url)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(aid) DO UPDATE SET
                    agent_card = excluded.agent_card,
                    name = excluded.name,
                    description = excluded.description,
                    url = excluded.url,
                    last_heartbeat = datetime('now')
                """,
                (aid, card_json, name, description, url),
            )
            # Replace capabilities
            await db.execute("DELETE FROM registry_capabilities WHERE aid = ?", (aid,))
            for cap in agent_card.get("capabilities", []):
                tags_str = ",".join(cap.get("tags", []))
                price = cap.get("pricing", {}).get("amount", 0)
                await db.execute(
                    """
                    INSERT INTO registry_capabilities (aid, name, description, price, tags)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        aid,
                        cap.get("name", cap.get("id", "")),
                        cap.get("description", ""),
                        price,
                        tags_str,
                    ),
                )
            await db.commit()

        self._cache[aid] = agent_card

    async def deregister_agent(self, aid: str) -> bool:
        """Remove an agent. Returns True if it existed."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            cursor = await db.execute("DELETE FROM registered_agents WHERE aid = ?", (aid,))
            await db.commit()
            removed = cursor.rowcount > 0

        if removed:
            self._cache.pop(aid, None)
        return removed

    # ── Heartbeat ──────────────────────────────────────────────

    async def heartbeat(self, aid: str) -> bool:
        """Update last_heartbeat timestamp. Returns True if agent found."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "UPDATE registered_agents SET last_heartbeat = datetime('now') WHERE aid = ?",
                (aid,),
            )
            await db.commit()
            return cursor.rowcount > 0

    # ── Queries ────────────────────────────────────────────────

    async def get_agent(self, aid: str) -> dict[str, Any] | None:
        """Retrieve an agent card by AID."""
        return self._cache.get(aid)

    async def search(self, query: str, *, max_price: int | None = None) -> list[dict[str, Any]]:
        """Search capabilities by keyword with optional price filter.

        Uses OR-matching across words (same pattern as CapabilityRegistry).
        """
        words = query.lower().split()
        if not words:
            return []

        conditions = []
        params: list[Any] = []
        for word in words:
            pattern = f"%{word}%"
            conditions.append(
                "(LOWER(rc.name) LIKE ? OR LOWER(rc.description) LIKE ? OR LOWER(rc.tags) LIKE ?)"
            )
            params.extend([pattern, pattern, pattern])

        where = " OR ".join(conditions)
        if max_price is not None:
            where = f"({where}) AND rc.price <= ?"
            params.append(max_price)

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                f"""
                SELECT DISTINCT rc.aid, rc.name, rc.description, rc.price, rc.tags,
                       ra.name AS agent_name, ra.url
                FROM registry_capabilities rc
                JOIN registered_agents ra ON rc.aid = ra.aid
                WHERE {where}
                """,
                params,
            )
            rows = await cursor.fetchall()

        return [
            {
                "aid": aid,
                "name": name,
                "description": desc,
                "price": price,
                "tags": tags,
                "agent_name": agent_name,
                "url": url,
            }
            for aid, name, desc, price, tags, agent_name, url in rows
        ]

    async def list_agents(self) -> list[dict[str, Any]]:
        """Return all registered agent cards."""
        return list(self._cache.values())

    # ── Maintenance ────────────────────────────────────────────

    async def prune_stale(self, max_age_seconds: float = 300.0) -> list[str]:
        """Remove agents whose last_heartbeat is older than max_age.

        Returns list of pruned AIDs.
        """
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            cursor = await db.execute(
                """
                SELECT aid FROM registered_agents
                WHERE last_heartbeat < datetime('now', ? || ' seconds')
                """,
                (f"-{int(max_age_seconds)}",),
            )
            stale_rows = await cursor.fetchall()
            stale_aids = [row[0] for row in stale_rows]

            if stale_aids:
                placeholders = ",".join("?" for _ in stale_aids)
                await db.execute(
                    f"DELETE FROM registered_agents WHERE aid IN ({placeholders})",
                    stale_aids,
                )
                await db.commit()

                for aid in stale_aids:
                    self._cache.pop(aid, None)

        return stale_aids

    async def agent_count(self) -> int:
        """Return total number of registered agents."""
        return len(self._cache)


__all__ = ["RegistryStore"]
