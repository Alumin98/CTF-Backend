import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

sys.path.append(str(Path(__file__).resolve().parents[1]))

if "aiosqlite" not in sys.modules:
    import sqlite3

    aiosqlite_stub = types.ModuleType("aiosqlite")

    async def _connect(*args, **kwargs):  # pragma: no cover - used only if someone hits the DB
        raise RuntimeError("aiosqlite is not installed in the test environment")

    aiosqlite_stub.connect = _connect
    for attr in (
        "Error",
        "Warning",
        "InterfaceError",
        "DatabaseError",
        "InternalError",
        "OperationalError",
        "ProgrammingError",
        "IntegrityError",
        "DataError",
        "NotSupportedError",
    ):
        setattr(aiosqlite_stub, attr, getattr(sqlite3, attr))

    aiosqlite_stub.sqlite_version = sqlite3.sqlite_version
    aiosqlite_stub.sqlite_version_info = sqlite3.sqlite_version_info

    sys.modules["aiosqlite"] = aiosqlite_stub

from app.routes.admin_challenges import require_admin  # noqa: E402


def test_require_admin_allows_role_admin():
    admin_user = SimpleNamespace(role="admin")

    async def _run():
        result = await require_admin(user=admin_user)
        return result

    result = asyncio.run(_run())
    assert result is admin_user


def test_require_admin_blocks_non_admin():
    regular_user = SimpleNamespace(role="player")

    async def _run():
        try:
            await require_admin(user=regular_user)
        except HTTPException as exc:
            return exc
        return None

    error = asyncio.run(_run())
    assert isinstance(error, HTTPException)
    assert error.status_code == 403
    assert "Admin only" in error.detail
