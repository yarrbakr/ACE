"""Shared fixtures for registry tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from registry.app import create_registry_app


@pytest.fixture()
def registry_db(tmp_path: Path) -> Path:
    return tmp_path / "test_registry.db"


@pytest.fixture()
def registry_client(registry_db: Path) -> TestClient:  # type: ignore[misc]
    app = create_registry_app(
        db_path=registry_db,
        prune_interval=9999.0,  # effectively disable pruning in tests
    )
    with TestClient(app) as tc:
        yield tc  # type: ignore[misc]


SAMPLE_AGENT_CARD: dict[str, Any] = {
    "name": "test-agent",
    "description": "A test agent for registry tests",
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
    "authentication": {"type": "ed25519", "public_key": "dGVzdGtleQ=="},
    "aid": "aid:testregistryagent",
}

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
    "authentication": {"type": "ed25519", "public_key": "c2Vjb25ka2V5"},
    "aid": "aid:translatoragent",
}
