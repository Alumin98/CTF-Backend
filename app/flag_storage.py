"""Utilities for hashing and verifying challenge flags."""

from __future__ import annotations

from passlib.context import CryptContext
from passlib.exc import UnknownHashError

_flag_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_flag(plain_flag: str) -> str:
    """Hash a challenge flag using Argon2.

    The result includes the salt and Argon2 parameters so that it can be
    verified later without reconfiguring the context.
    """

    if plain_flag is None:
        raise ValueError("Flag must be a non-null string")
    return _flag_context.hash(plain_flag)


def verify_flag(plain_flag: str, stored_hash: str | None) -> bool:
    """Return True when ``plain_flag`` matches ``stored_hash``.

    ``stored_hash`` may be ``None`` (for challenges without a flag) or an
    Argon2 hash produced by :func:`hash_flag`.  Verification is delegated to
    Passlib so that comparisons are constant-time and resistant to timing
    attacks.
    """

    if not stored_hash:
        return False
    try:
        return _flag_context.verify(plain_flag, stored_hash)
    except UnknownHashError:
        # Legacy deployments might still have SHA-256 hex digests stored.
        # Fall back to a constant-time comparison of the hex digests so that
        # existing data continues to work until it is re-saved by an admin.
        import hashlib
        import hmac

        candidate = hashlib.sha256((plain_flag or "").encode("utf-8")).hexdigest()
        return hmac.compare_digest(candidate, stored_hash)
