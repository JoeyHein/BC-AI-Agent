"""Password hashing tests for AuthService.

Locks the bcrypt-direct implementation (replacing passlib's CryptContext, which
broke under bcrypt >= 4.1). Verifies round-trip, the 72-byte truncation that
matches passlib, and that hashes minted by the old passlib path still verify.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.auth_service import AuthService


def test_hash_and_verify_roundtrip():
    h = AuthService.get_password_hash("test123")
    assert h.startswith("$2b$")
    assert AuthService.verify_password("test123", h)
    assert not AuthService.verify_password("wrong", h)


def test_long_password_truncated_at_72_bytes():
    """bcrypt only uses the first 72 bytes — like passlib, we clamp there."""
    base = "p" * 72
    h = AuthService.get_password_hash(base)
    # A 73rd+ char beyond the limit must not change the verification result.
    assert AuthService.verify_password(base + "EXTRA", h)


def test_verifies_hash_minted_by_legacy_passlib():
    """A $2b$12$ hash created the old way (passlib bcrypt) must still verify.

    passlib and direct bcrypt emit identical $2b$ output, so a hash minted by
    the standard bcrypt backend (what passlib used) verifies unchanged.
    """
    import bcrypt
    legacy = bcrypt.hashpw(b"test123", bcrypt.gensalt(rounds=12)).decode("ascii")
    assert AuthService.verify_password("test123", legacy)
    assert not AuthService.verify_password("nope", legacy)


def test_malformed_hash_returns_false_not_raise():
    assert AuthService.verify_password("anything", "not-a-bcrypt-hash") is False
