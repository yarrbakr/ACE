"""Signature verification middleware for the ACE API.

Verifies Ed25519 signatures on mutation endpoints (POST/PUT/DELETE).
GET/HEAD/OPTIONS requests pass through without signature checks.
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING, Any

import aiosqlite
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _error_json(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "error": {"code": code, "message": message},
        },
    )


async def _lookup_public_key(
    db_path: Any, agent_id: str
) -> Ed25519PublicKey | None:
    """Look up an agent's public key from the agents table."""
    try:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT public_key FROM agents WHERE aid = ?", (agent_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            raw = base64.b64decode(row["public_key"])
            return Ed25519PublicKey.from_public_bytes(raw)
    except Exception:
        logger.debug("Failed to look up public key for %s", agent_id)
        return None


class SignatureVerificationMiddleware(BaseHTTPMiddleware):
    """Verify Ed25519 signatures on mutation requests.

    Checks:
    1. X-Agent-ID header present
    2. X-Signature header present (base64-encoded Ed25519 signature)
    3. Agent exists in registry OR matches local identity
    4. Signature valid against raw request body
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method in _SAFE_METHODS:
            return await call_next(request)

        agent_id = request.headers.get("X-Agent-ID")
        signature_b64 = request.headers.get("X-Signature")

        if not agent_id:
            return _error_json(
                "UNAUTHORIZED", "Missing X-Agent-ID header", 401
            )
        if not signature_b64:
            return _error_json(
                "UNAUTHORIZED", "Missing X-Signature header", 401
            )

        # Read body for signature verification
        body = await request.body()

        # Resolve public key: local identity first, then registry
        public_key: Ed25519PublicKey | None = None

        identity = getattr(request.app.state, "identity", None)
        if identity is not None and identity.aid == agent_id:
            public_key = identity._public_key  # noqa: SLF001

        if public_key is None:
            db_path = getattr(request.app.state, "db_path", None)
            if db_path is not None:
                public_key = await _lookup_public_key(db_path, agent_id)

        if public_key is None:
            return _error_json(
                "UNAUTHORIZED",
                f"Unknown agent: {agent_id}",
                401,
            )

        # Verify signature
        try:
            sig_bytes = base64.b64decode(signature_b64)
            public_key.verify(sig_bytes, body)
        except Exception:
            return _error_json(
                "FORBIDDEN", "Invalid signature", 403
            )

        # Store verified agent ID for downstream handlers
        request.state.verified_agent_id = agent_id
        return await call_next(request)


def add_signature_middleware(app: FastAPI) -> None:
    """Register the signature verification middleware on the app."""
    app.add_middleware(SignatureVerificationMiddleware)
