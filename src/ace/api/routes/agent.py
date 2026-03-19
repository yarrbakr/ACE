"""Agent registration and agent card endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiosqlite
from fastapi import APIRouter, Depends, Request

from ace.api.deps import get_capability_registry, get_identity, get_settings
from ace.api.models import ErrorResponse

if TYPE_CHECKING:
    from ace.core.capability import CapabilityRegistry
    from ace.core.config import AceSettings
    from ace.core.identity import AgentIdentity

router = APIRouter()


@router.post(
    "/register",
    status_code=201,
    summary="Register this agent with the network",
    responses={409: {"model": ErrorResponse}},
)
async def register_agent(
    request: Request,
    identity: AgentIdentity = Depends(get_identity),
    settings: AceSettings = Depends(get_settings),
    registry: CapabilityRegistry = Depends(get_capability_registry),
) -> dict[str, Any]:
    """Register the local agent in the capability registry and agents table."""
    agent_id = request.state.verified_agent_id
    aid = identity.aid
    if agent_id != aid:
        return {
            "status": "error",
            "error": {
                "code": "FORBIDDEN",
                "message": "Can only register yourself",
            },
        }

    # Upsert into agents table
    db_path = request.app.state.db_path
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute(
            """INSERT INTO agents (aid, name, description, public_key, endpoint_url)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(aid) DO UPDATE SET
                 name = excluded.name,
                 description = excluded.description,
                 public_key = excluded.public_key,
                 endpoint_url = excluded.endpoint_url,
                 updated_at = datetime('now')""",
            (
                aid,
                settings.agent_name,
                settings.agent_description,
                identity.public_key_b64,
                f"http://127.0.0.1:{settings.port}",
            ),
        )
        await db.commit()

    # Register agent card in capability registry
    skills = await registry.list_skills()
    card = {
        "name": settings.agent_name,
        "description": settings.agent_description,
        "url": f"http://127.0.0.1:{settings.port}",
        "capabilities": [
            {
                "id": s["name"],
                "name": s["name"].replace("_", " ").replace("-", " ").title(),
                "description": s.get("description", ""),
                "pricing": {
                    "currency": s.get("currency", "AGC"),
                    "model": s.get("pricing_model", "per_call"),
                    "amount": s.get("price", 0),
                },
            }
            for s in skills
        ],
        "authentication": {
            "type": "ed25519",
            "public_key": identity.public_key_b64,
        },
        "aid": aid,
    }
    await registry.register(aid, card)

    return {"status": "ok", "aid": aid, "registered": True}


@router.get(
    "/{aid}",
    summary="Retrieve an agent's card by AID",
    responses={404: {"model": ErrorResponse}},
)
async def get_agent_card(
    aid: str,
    registry: CapabilityRegistry = Depends(get_capability_registry),
) -> dict[str, Any]:
    """Look up an agent's public profile and capabilities."""
    card = await registry.get_agent_card(aid)
    if card is None:
        return {
            "status": "error",
            "error": {"code": "NOT_FOUND", "message": f"Agent not found: {aid}"},
        }
    return {"status": "ok", "agent": card}
