"""FastAPI dependency injection — pulls core instances from lifespan state.

All dependencies read from request.app.state, which is populated during
the application lifespan context in server.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request

    from ace.core.capability import CapabilityRegistry
    from ace.core.config import AceSettings
    from ace.core.escrow import EscrowManager
    from ace.core.identity import AgentIdentity
    from ace.core.ledger import Ledger
    from ace.core.transaction import TransactionEngine


def get_settings(request: Request) -> AceSettings:
    """Provide the AceSettings from lifespan state."""
    return request.app.state.settings  # type: ignore[no-any-return]


def get_ledger(request: Request) -> Ledger:
    """Provide the shared Ledger instance."""
    return request.app.state.ledger  # type: ignore[no-any-return]


def get_escrow_manager(request: Request) -> EscrowManager:
    """Provide the shared EscrowManager instance."""
    return request.app.state.escrow_manager  # type: ignore[no-any-return]


def get_transaction_engine(request: Request) -> TransactionEngine:
    """Provide the shared TransactionEngine instance."""
    return request.app.state.transaction_engine  # type: ignore[no-any-return]


def get_capability_registry(request: Request) -> CapabilityRegistry:
    """Provide the shared CapabilityRegistry instance."""
    return request.app.state.capability_registry  # type: ignore[no-any-return]


def get_identity(request: Request) -> AgentIdentity:
    """Provide the local AgentIdentity."""
    return request.app.state.identity  # type: ignore[no-any-return]


__all__ = [
    "get_settings",
    "get_ledger",
    "get_escrow_manager",
    "get_transaction_engine",
    "get_capability_registry",
    "get_identity",
]
