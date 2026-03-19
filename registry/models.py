"""Pydantic v2 request/response models for the ACE public registry."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RegisterAgentRequest(BaseModel):
    """Payload for POST /register."""

    aid: str = Field(description="Agent ID")
    agent_card: dict[str, Any] = Field(description="Full A2A agent card JSON")


class HeartbeatRequest(BaseModel):
    """Payload for POST /heartbeat."""

    aid: str = Field(description="Agent ID")


class DeregisterRequest(BaseModel):
    """Payload for POST /deregister."""

    aid: str = Field(description="Agent ID")


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
