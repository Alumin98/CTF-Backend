"""Utilities for hashing and verifying challenge flags."""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional

from passlib.context import CryptContext


_PWD_CONTEXT = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_flag(flag: str) -> str:
    """Hash a flag value using Argon2."""
    if flag is None:
        raise ValueError("flag must not be None")
    return _PWD_CONTEXT.hash(flag)


def _verify_legacy_sha256(flag: str, stored_hash: str) -> bool:
    digest = hashlib.sha256(flag.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, stored_hash)


def verify_flag(flag: str, stored_hash: Optional[str]) -> bool:
    """Verify a submitted flag against a stored hash.

    Supports Argon2 (preferred) and falls back to legacy SHA-256 hashes so
    existing databases continue to work without migration.
    """

    if not stored_hash:
        return False

    if stored_hash.startswith("$argon2"):
        try:
            return _PWD_CONTEXT.verify(flag, stored_hash)
        except ValueError:
            return False

    return _verify_legacy_sha256(flag, stored_hash)


__all__ = ["hash_flag", "verify_flag"]
