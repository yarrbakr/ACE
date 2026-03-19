"""Discovery / search endpoints — powered by CapabilityRegistry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query, Request

from ace.api.deps import get_capability_registry, get_identity, get_settings
from ace.api.models import (
    CapabilitySearchResponse,
    ErrorResponse,
    RegisterCapabilityRequest,
)
from ace.core.capability import (
    CapabilityRegistry,
    SkillDefinition,
    SkillPricing,
    generate_agent_card,
)

if TYPE_CHECKING:
    from ace.core.config import AceSettings
    from ace.core.identity import AgentIdentity

router = APIRouter()


@router.get(
    "/search",
    summary="Search for capabilities across the agent network",
    response_model=CapabilitySearchResponse,
)
async def search_capabilities(
    q: str = Query(description="Search query"),
    max_price: int | None = Query(default=None, description="Maximum price filter"),
    currency: str | None = Query(default=None, description="Currency filter"),
    registry: CapabilityRegistry = Depends(get_capability_registry),
) -> CapabilitySearchResponse:
    """Search for agent capabilities by keyword with optional price filter."""
    results = await registry.search(q, max_price=max_price)
    return CapabilitySearchResponse(results=results)


@router.post(
    "/capabilities",
    status_code=201,
    summary="Register a capability (skill)",
    responses={422: {"model": ErrorResponse}},
)
async def register_capability(
    body: RegisterCapabilityRequest,
    request: Request,
    identity: AgentIdentity = Depends(get_identity),
    settings: AceSettings = Depends(get_settings),
    registry: CapabilityRegistry = Depends(get_capability_registry),
) -> dict[str, Any]:
    """Register a new capability for this agent."""
    aid = identity.aid

    skill = SkillDefinition(
        name=body.name,
        description=body.description,
        version=body.version,
        tags=body.tags,
        parameters=body.parameters,
        returns=body.returns,
        pricing=SkillPricing(
            currency=body.currency,
            model=body.pricing_model,
            amount=body.price,
        ),
    )

    card = generate_agent_card(
        name=settings.agent_name,
        description=settings.agent_description,
        url=f"http://127.0.0.1:{settings.port}",
        skills=[skill],
        aid=aid,
        public_key_b64=identity.public_key_b64,
    )
    await registry.register(aid, card)

    return {"status": "ok", "capability": body.name, "registered": True}


@router.get(
    "/agents",
    summary="List all known agents in the network",
)
async def list_agents(
    registry: CapabilityRegistry = Depends(get_capability_registry),
) -> list[dict[str, Any]]:
    """List all registered agents."""
    return await registry.list_all()
