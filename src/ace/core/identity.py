"""Identity module — Ed25519 key management, AID generation, and signing."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from ace.core.exceptions import DecryptionError

PBKDF2_ITERATIONS = 200_000
SALT_LENGTH = 16


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte Fernet key from password + salt via PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


class AgentIdentity:
    """Ed25519 identity — key generation, AID derivation, signing, and verification."""

    def __init__(self, private_key: Ed25519PrivateKey | None = None) -> None:
        self._private_key = private_key or Ed25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()

    # ── AID derivation ──────────────────────────────────────────

    @property
    def aid(self) -> str:
        digest = hashlib.sha256(self.public_key_bytes).digest()
        encoded = base64.b32encode(digest[:16]).decode("ascii").lower().rstrip("=")
        return f"aid:{encoded}"

    # ── Signing & verification ──────────────────────────────────

    def sign(self, message: bytes) -> bytes:
        return self._private_key.sign(message)

    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            self._public_key.verify(signature, message)
            return True
        except (InvalidSignature, Exception):
            return False

    @staticmethod
    def verify_with_public_key(
        public_key: Ed25519PublicKey, message: bytes, signature: bytes,
    ) -> bool:
        try:
            public_key.verify(signature, message)
            return True
        except (InvalidSignature, Exception):
            return False

    # ── Encrypted key persistence ───────────────────────────────

    def save_encrypted(self, path: Path, password: str) -> None:
        salt = os.urandom(SALT_LENGTH)
        fernet_key = _derive_fernet_key(password, salt)
        fernet = Fernet(fernet_key)
        raw_private = self._private_key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption(),
        )
        encrypted = fernet.encrypt(raw_private)
        path.write_bytes(salt + encrypted)

    @classmethod
    def load_encrypted(cls, path: Path, password: str) -> AgentIdentity:
        try:
            data = path.read_bytes()
            if len(data) <= SALT_LENGTH:
                raise DecryptionError("Identity file is corrupted or unreadable.")
            salt = data[:SALT_LENGTH]
            encrypted = data[SALT_LENGTH:]
            fernet_key = _derive_fernet_key(password, salt)
            fernet = Fernet(fernet_key)
            raw_private = fernet.decrypt(encrypted)
            private_key = Ed25519PrivateKey.from_private_bytes(raw_private)
            return cls(private_key)
        except DecryptionError:
            raise
        except (InvalidToken, ValueError, Exception):
            raise DecryptionError("Identity file is corrupted or unreadable.") from None

    # ── Public key accessors ────────────────────────────────────

    @property
    def public_key_bytes(self) -> bytes:
        return self._public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self.public_key_bytes).decode("ascii")


__all__ = ["AgentIdentity", "PBKDF2_ITERATIONS", "SALT_LENGTH"]
