"""Pydantic request / response models for the ACE REST API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── Error envelope ──────────────────────────────────────────


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    status: str = "error"
    error: ErrorDetail


# ── Transaction models ──────────────────────────────────────


class CreateTransactionRequest(BaseModel):
    seller_aid: str = Field(description="AID of the seller agent")
    capability_id: str = Field(description="ID of the capability to purchase")


class SubmitQuoteRequest(BaseModel):
    price: int = Field(gt=0, description="Price in AGC tokens")


class DeliverResultRequest(BaseModel):
    result_hash: str = Field(description="SHA-256 hash of the delivered result")


class DisputeRequest(BaseModel):
    reason: str = Field(default="", description="Reason for the dispute")


class TransactionResponse(BaseModel):
    status: str = "ok"
    transaction: dict[str, Any]


class TransactionListResponse(BaseModel):
    status: str = "ok"
    transactions: list[dict[str, Any]]


# ── Discovery models ───────────────────────────────────────


class RegisterCapabilityRequest(BaseModel):
    name: str
    description: str = ""
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    returns: str = ""
    price: int = Field(gt=0, description="Price in AGC tokens")
    pricing_model: str = Field(default="per_call")
    currency: str = Field(default="AGC")


class CapabilitySearchResponse(BaseModel):
    status: str = "ok"
    results: list[dict[str, Any]]


# ── Admin models ────────────────────────────────────────────


class BalanceResponse(BaseModel):
    status: str = "ok"
    aid: str
    balance: int


class HistoryEntry(BaseModel):
    entry_id: str
    transaction_id: str
    timestamp: str
    direction: str
    amount: int
    balance_after: int
    entry_type: str
    description: str


class HistoryResponse(BaseModel):
    status: str = "ok"
    aid: str
    entries: list[HistoryEntry]


class StatusResponse(BaseModel):
    status: str = "ok"
    aid: str
    agent_name: str
    port: int
    uptime_seconds: float
    skills_count: int
    active_transactions: int
    discovery_mode: str = "centralized"
    known_peers: int = 0
    seed_peers: list[str] = Field(default_factory=list)


# ── Agent models ────────────────────────────────────────────


class AgentCardResponse(BaseModel):
    """A2A-compatible agent card."""

    name: str
    description: str
    url: str
    capabilities: list[dict[str, Any]]
    authentication: dict[str, str]
    aid: str
