"""Shared fixtures for registry tests."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ace.core.identity import AgentIdentity
from registry.app import create_registry_app
from registry.routes import _rate_limit


@pytest.fixture(autouse=True)
def _clear_rate_limits() -> None:
    """Clear rate-limit state before every test to prevent cross-test pollution."""
    _rate_limit.clear()


@pytest.fixture()
def registry_db(tmp_path: Path) -> Path:
    return tmp_path / "test_registry.db"


@pytest.fixture()
def registry_identity() -> AgentIdentity:
    """Generate a fresh Ed25519 identity for registry tests."""
    return AgentIdentity()


@pytest.fixture()
def registry_client(registry_db: Path) -> TestClient:  # type: ignore[misc]
    app = create_registry_app(
        db_path=registry_db,
        prune_interval=9999.0,  # effectively disable pruning in tests
    )
    with TestClient(app) as tc:
        yield tc  # type: ignore[misc]


def make_agent_card(identity: AgentIdentity, *, name: str = "test-agent") -> dict[str, Any]:
    """Build an agent card with the given identity's public key."""
    return {
        "name": name,
        "description": f"A test agent ({name})",
        "url": "http://localhost:8080",
        "capabilities": [
            {
                "id": "code_review",
                "name": "Code Review",
                "description": "Reviews Python code for quality",
                "pricing": {"currency": "AGC", "model": "per_call", "amount": 50},
                "tags": ["python", "review"],
            }
        ],
        "authentication": {"type": "ed25519", "public_key": identity.public_key_b64},
        "aid": identity.aid,
    }


SAMPLE_AGENT_CARD_2_IDENTITY = AgentIdentity()

SAMPLE_AGENT_CARD_2: dict[str, Any] = {
    "name": "translator-agent",
    "description": "Translates text between languages",
    "url": "http://localhost:8081",
    "capabilities": [
        {
            "id": "translate",
            "name": "Translation",
            "description": "Translates text between 50+ languages",
            "pricing": {"currency": "AGC", "model": "per_call", "amount": 30},
            "tags": ["translation", "nlp", "language"],
        },
        {
            "id": "summarize",
            "name": "Summarization",
            "description": "Summarizes long documents into key points",
            "pricing": {"currency": "AGC", "model": "per_call", "amount": 100},
            "tags": ["nlp", "summarization"],
        },
    ],
    "authentication": {
        "type": "ed25519",
        "public_key": SAMPLE_AGENT_CARD_2_IDENTITY.public_key_b64,
    },
    "aid": SAMPLE_AGENT_CARD_2_IDENTITY.aid,
}


def signed_post(
    tc: TestClient,
    path: str,
    payload: dict[str, Any],
    identity: AgentIdentity,
    *,
    expected_status: int | None = None,
) -> Any:
    """POST JSON to the registry with Ed25519 signature headers."""
    body_bytes = json.dumps(payload, separators=(",", ":")).encode()
    sig = identity.sign(body_bytes)
    headers = {
        "X-Agent-ID": identity.aid,
        "X-Signature": base64.b64encode(sig).decode(),
        "Content-Type": "application/json",
    }
    resp = tc.post(path, content=body_bytes, headers=headers)
    if expected_status is not None:
        assert resp.status_code == expected_status, (
            f"Expected {expected_status}, got {resp.status_code}: {resp.text}"
        )
    return resp


# Legacy constant for backward compat (now uses a real identity)
_LEGACY_IDENTITY = AgentIdentity()
SAMPLE_AGENT_CARD: dict[str, Any] = make_agent_card(_LEGACY_IDENTITY)
