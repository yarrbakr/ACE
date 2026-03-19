"""Centralized custom exceptions for the ACE system."""


class ACEError(Exception):
    """Base exception for all ACE errors."""


class InsufficientBalanceError(ACEError):
    """Raised when an agent lacks funds for a transfer or escrow lock."""


class AccountNotFoundError(ACEError):
    """Raised when an account lookup fails for a given AID."""


class InvalidEscrowStateError(ACEError):
    """Raised when an escrow operation is invalid for the current state."""


class InvalidTransitionError(ACEError):
    """Raised when a transaction state-machine transition is not allowed."""


class UnauthorizedActionError(ACEError):
    """Raised when an actor is not authorized for a transaction action."""


class ConfigNotFoundError(ACEError):
    """Raised when the ACE configuration directory or file is missing."""


class SkillParseError(ACEError):
    """Raised when a SKILL.md file cannot be parsed."""


class IdentityError(ACEError):
    """Base exception for identity and key-management failures."""


class DecryptionError(IdentityError):
    """Raised when key decryption fails (wrong password or corrupted file)."""


__all__ = [
    "ACEError",
    "AccountNotFoundError",
    "InsufficientBalanceError",
    "InvalidEscrowStateError",
    "InvalidTransitionError",
    "UnauthorizedActionError",
    "ConfigNotFoundError",
    "SkillParseError",
    "IdentityError",
    "DecryptionError",
]
