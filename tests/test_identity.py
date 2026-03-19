"""Comprehensive tests for the AgentIdentity module."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ace.core.exceptions import DecryptionError
from ace.core.identity import AgentIdentity

TEST_PASSWORD = "super-secret-test-pw-123"


class TestKeyGeneration:
    """Ed25519 key pair generation."""

    def test_generates_valid_key_pair(self) -> None:
        identity = AgentIdentity()
        assert identity.public_key_bytes is not None
        assert len(identity.public_key_bytes) == 32

    def test_different_instances_have_different_keys(self) -> None:
        a = AgentIdentity()
        b = AgentIdentity()
        assert a.public_key_bytes != b.public_key_bytes


class TestAidDerivation:
    """Agent ID derivation from public key."""

    def test_aid_is_deterministic(self) -> None:
        identity = AgentIdentity()
        assert identity.aid == identity.aid

    def test_aid_format_matches_spec(self) -> None:
        identity = AgentIdentity()
        assert re.fullmatch(r"aid:[a-z2-7]+", identity.aid)

    def test_aid_starts_with_prefix(self) -> None:
        identity = AgentIdentity()
        assert identity.aid.startswith("aid:")

    def test_different_keys_produce_different_aids(self) -> None:
        aids = {AgentIdentity().aid for _ in range(100)}
        assert len(aids) == 100

    def test_same_key_always_same_aid(self) -> None:
        identity = AgentIdentity()
        aids = [identity.aid for _ in range(10)]
        assert len(set(aids)) == 1


class TestSigning:
    """Signing and verification."""

    def test_sign_then_verify(self) -> None:
        identity = AgentIdentity()
        msg = b"hello world"
        sig = identity.sign(msg)
        assert identity.verify(msg, sig) is True

    def test_tampered_message_fails(self) -> None:
        identity = AgentIdentity()
        sig = identity.sign(b"original")
        assert identity.verify(b"tampered", sig) is False

    def test_wrong_key_fails(self) -> None:
        alice = AgentIdentity()
        bob = AgentIdentity()
        sig = alice.sign(b"from alice")
        assert bob.verify(b"from alice", sig) is False

    def test_empty_message_sign_verify(self) -> None:
        identity = AgentIdentity()
        sig = identity.sign(b"")
        assert identity.verify(b"", sig) is True

    def test_empty_signature_returns_false(self) -> None:
        identity = AgentIdentity()
        assert identity.verify(b"message", b"") is False

    def test_garbage_signature_returns_false(self) -> None:
        identity = AgentIdentity()
        assert identity.verify(b"message", b"not-a-valid-signature") is False

    def test_verify_never_raises(self) -> None:
        identity = AgentIdentity()
        result = identity.verify(b"msg", b"\x00" * 64)
        assert result is False


class TestEncryptedPersistence:
    """Save/load with PBKDF2 + Fernet encryption."""

    def test_round_trip(self, tmp_path: Path) -> None:
        original = AgentIdentity()
        key_path = tmp_path / "identity.key"
        original.save_encrypted(key_path, TEST_PASSWORD)
        loaded = AgentIdentity.load_encrypted(key_path, TEST_PASSWORD)
        assert loaded.aid == original.aid
        assert loaded.public_key_bytes == original.public_key_bytes

    def test_sign_verify_after_round_trip(self, tmp_path: Path) -> None:
        original = AgentIdentity()
        key_path = tmp_path / "identity.key"
        original.save_encrypted(key_path, TEST_PASSWORD)
        loaded = AgentIdentity.load_encrypted(key_path, TEST_PASSWORD)
        msg = b"persistence test"
        sig = original.sign(msg)
        assert loaded.verify(msg, sig) is True

    def test_wrong_password_raises_decryption_error(self, tmp_path: Path) -> None:
        identity = AgentIdentity()
        key_path = tmp_path / "identity.key"
        identity.save_encrypted(key_path, TEST_PASSWORD)
        with pytest.raises(DecryptionError):
            AgentIdentity.load_encrypted(key_path, "wrong-password")

    def test_corrupted_file_raises_decryption_error(self, tmp_path: Path) -> None:
        key_path = tmp_path / "identity.key"
        key_path.write_bytes(b"corrupted garbage data here!!")
        with pytest.raises(DecryptionError):
            AgentIdentity.load_encrypted(key_path, TEST_PASSWORD)

    def test_truncated_file_raises_decryption_error(self, tmp_path: Path) -> None:
        key_path = tmp_path / "identity.key"
        key_path.write_bytes(b"\x00" * 10)  # shorter than SALT_LENGTH
        with pytest.raises(DecryptionError):
            AgentIdentity.load_encrypted(key_path, TEST_PASSWORD)

    def test_saved_file_is_not_empty(self, tmp_path: Path) -> None:
        identity = AgentIdentity()
        key_path = tmp_path / "identity.key"
        identity.save_encrypted(key_path, TEST_PASSWORD)
        assert key_path.stat().st_size > 0


class TestPublicKeyAccessors:
    """Public key bytes and base64 accessors."""

    def test_public_key_bytes_length(self) -> None:
        identity = AgentIdentity()
        assert len(identity.public_key_bytes) == 32

    def test_public_key_b64_is_decodable(self) -> None:
        import base64

        identity = AgentIdentity()
        decoded = base64.b64decode(identity.public_key_b64)
        assert decoded == identity.public_key_bytes
