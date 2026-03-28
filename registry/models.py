"""Pydantic v2 request/response models for the ACE public registry."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

_MAX_AGENT_CARD_BYTES = 65_536  # 64 KB


class RegisterAgentRequest(BaseModel):
    """Payload for POST /register."""

    aid: str = Field(description="Agent ID", max_length=256)
    agent_card: dict[str, Any] = Field(description="Full A2A agent card JSON")

    @field_validator("agent_card")
    @classmethod
    def _card_size_limit(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v)) > _MAX_AGENT_CARD_BYTES:
            raise ValueError("agent_card exceeds 64KB size limit")
        return v


class HeartbeatRequest(BaseModel):
    """Payload for POST /heartbeat."""

    aid: str = Field(description="Agent ID", max_length=256)


class DeregisterRequest(BaseModel):
    """Payload for POST /deregister."""

    aid: str = Field(description="Agent ID", max_length=256)


class SearchResponse(BaseModel):
    """Response for GET /search."""

    status: str = "ok"
    results: list[dict[str, Any]] = Field(default_factory=list)


class AgentListResponse(BaseModel):
    """Response for GET /agents."""

    status: str = "ok"
    agents: list[dict[str, Any]] = Field(default_factory=list)


class RegistryStatsResponse(BaseModel):
    """Response for GET /health."""

    status: str = "ok"
    version: str
    agent_count: int
    uptime_seconds: float
