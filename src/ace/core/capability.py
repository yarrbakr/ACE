"""Capability module — SKILL.md parser, Agent Card generation, and registry."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

import aiosqlite
import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ace.core.exceptions import SkillParseError

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


# ── Pydantic models ─────────────────────────────────────────


class SkillPricing(BaseModel):
    """Pricing information for a skill."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"currency": "AGC", "model": "per_call", "amount": 50}]}
    )

    currency: str = "AGC"
    model: Literal["per_call", "per_token", "hourly", "subscription"] = "per_call"
    amount: int

    @field_validator("amount")
    @classmethod
    def _positive_amount(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount must be greater than 0")
        return v


class SkillDefinition(BaseModel):
    """Structured representation of a parsed SKILL.md file."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "python_code_generation",
                    "version": "1.0.0",
                    "description": "Generate Python code from natural language",
                    "parameters": {"prompt": {"type": "string"}},
                    "returns": {"code": {"type": "string"}},
                    "pricing": {"currency": "AGC", "model": "per_call", "amount": 50},
                    "tags": ["python", "code-generation"],
                }
            ]
        }
    )

    name: str
    version: str
    description: str
    parameters: dict[str, Any] = {}
    returns: dict[str, Any] = {}
    pricing: SkillPricing
    examples: list[dict[str, Any]] = []
    tags: list[str] = []
    body: str = ""

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not v or not _NAME_RE.match(v):
            raise ValueError(
                "name must be non-empty, start with a letter, "
                "and contain only alphanumeric, underscores, or hyphens"
            )
        return v

    @field_validator("version")
    @classmethod
    def _valid_version(cls, v: str) -> str:
        if not _SEMVER_RE.match(v):
            raise ValueError("version must follow semver (X.Y.Z)")
        return v

    @field_validator("description")
    @classmethod
    def _valid_description(cls, v: str) -> str:
        if not v:
            raise ValueError("description must not be empty")
        if len(v) > 500:
            raise ValueError("description must be at most 500 characters")
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def _normalize_tags(cls, v: list[str]) -> list[str]:
        return [t.lower().strip() for t in v]

    @model_validator(mode="before")
    @classmethod
    def _coerce_pricing(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Support shorthand: `price: 50` → full pricing block."""
        if isinstance(values, dict) and "price" in values and "pricing" not in values:
            values["pricing"] = {
                "currency": "AGC",
                "model": "per_call",
                "amount": values.pop("price"),
            }
        return values


# ── SKILL.md parser ──────────────────────────────────────────


class SkillParser:
    """Parses SKILL.md files with YAML frontmatter."""

    @staticmethod
    def parse(content: str) -> SkillDefinition:
        """Parse a SKILL.md string into a SkillDefinition."""
        parts = content.split("---")
        if len(parts) < 3:
            raise SkillParseError(
                "Invalid SKILL.md format: missing YAML frontmatter between --- markers"
            )

        frontmatter_raw = parts[1].strip()
        if not frontmatter_raw:
            raise SkillParseError("SKILL.md frontmatter is empty")

        try:
            data = yaml.safe_load(frontmatter_raw)
        except yaml.YAMLError as exc:
            raise SkillParseError(f"Invalid YAML in frontmatter: {exc}") from exc

        if not isinstance(data, dict):
            raise SkillParseError("SKILL.md frontmatter must be a YAML mapping")

        body = "---".join(parts[2:]).strip()
        data["body"] = body

        try:
            return SkillDefinition(**data)
        except Exception as exc:
            raise SkillParseError(f"Validation failed: {exc}") from exc


# ── Agent Card generator ─────────────────────────────────────


def generate_agent_card(
    *,
    name: str,
    description: str,
    url: str,
    skills: list[SkillDefinition],
    aid: str,
    public_key_b64: str,
) -> dict[str, Any]:
    """Build an A2A-compatible Agent Card with pricing extensions."""
    capabilities = [
        {
            "id": skill.name,
            "name": skill.name.replace("_", " ").replace("-", " ").title(),
            "description": skill.description,
            "parameters": skill.parameters,
            "returns": skill.returns,
            "pricing": skill.pricing.model_dump(),
            "tags": skill.tags,
            "version": skill.version,
        }
        for skill in skills
    ]
    return {
        "name": name,
        "description": description,
        "url": url,
        "capabilities": capabilities,
        "authentication": {
            "type": "ed25519",
            "public_key": public_key_b64,
        },
        "aid": aid,
    }


# ── Capability Registry (SQLite-backed) ──────────────────────

_REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_registry (
    aid         TEXT NOT NULL,
    agent_card  TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price       INTEGER NOT NULL DEFAULT 0,
    tags        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (aid, name)
);
CREATE INDEX IF NOT EXISTS idx_registry_name ON skill_registry(name);
CREATE INDEX IF NOT EXISTS idx_registry_price ON skill_registry(price);
"""


class CapabilityRegistry:
    """Registry of agent capabilities — in-memory cache + SQLite persistence."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._cache: dict[str, dict[str, Any]] = {}

    async def initialize(self) -> None:
        """Create registry table if needed and load cache."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.executescript(_REGISTRY_SCHEMA)
            await db.commit()
        await self._load_cache()

    async def _load_cache(self) -> None:
        """Populate in-memory cache from SQLite."""
        self._cache.clear()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("SELECT DISTINCT aid, agent_card FROM skill_registry")
            rows = await cursor.fetchall()
            for aid, card_json in rows:
                self._cache[aid] = json.loads(card_json)

    async def register(self, aid: str, agent_card: dict[str, Any]) -> None:
        """Store an agent's capabilities. Overwrites existing for same AID."""
        card_json = json.dumps(agent_card)

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM skill_registry WHERE aid = ?", (aid,))
            for cap in agent_card.get("capabilities", []):
                tags_str = ",".join(cap.get("tags", []))
                price = cap.get("pricing", {}).get("amount", 0)
                await db.execute(
                    """
                    INSERT INTO skill_registry (aid, agent_card, name, description, price, tags)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (aid, card_json, cap["name"], cap.get("description", ""), price, tags_str),
                )
            await db.commit()

        self._cache[aid] = agent_card

    async def unregister(self, aid: str) -> None:
        """Remove an agent from the registry."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM skill_registry WHERE aid = ?", (aid,))
            await db.commit()
        self._cache.pop(aid, None)

    async def get_agent_card(self, aid: str) -> dict[str, Any] | None:
        """Retrieve an agent card by AID."""
        return self._cache.get(aid)

    async def search(
        self,
        query: str,
        *,
        max_price: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search capabilities by keyword (OR-match across words)."""
        words = query.lower().split()
        if not words:
            return []

        conditions = []
        params: list[Any] = []
        for word in words:
            pattern = f"%{word}%"
            conditions.append(
                "(LOWER(name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(tags) LIKE ?)"
            )
            params.extend([pattern, pattern, pattern])

        where = " OR ".join(conditions)
        if max_price is not None:
            where = f"({where}) AND price <= ?"
            params.append(max_price)

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                f"SELECT DISTINCT aid, agent_card, name, price, tags FROM skill_registry WHERE {where}",
                params,
            )
            rows = await cursor.fetchall()

        results = []
        for aid, _card_json, name, price, tags in rows:
            results.append(
                {
                    "aid": aid,
                    "name": name,
                    "price": price,
                    "tags": tags,
                }
            )
        return results

    async def list_all(self) -> list[dict[str, Any]]:
        """Return all registered agent cards."""
        return list(self._cache.values())

    async def list_skills(self) -> list[dict[str, Any]]:
        """Return flat list of all registered skills with their AIDs."""
        results = []
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT aid, name, description, price, tags FROM skill_registry ORDER BY name"
            )
            rows = await cursor.fetchall()
        for aid, name, description, price, tags in rows:
            results.append(
                {
                    "aid": aid,
                    "name": name,
                    "description": description,
                    "price": price,
                    "tags": tags,
                }
            )
        return results


__all__ = [
    "CapabilityRegistry",
    "SkillDefinition",
    "SkillParser",
    "SkillPricing",
    "generate_agent_card",
]
