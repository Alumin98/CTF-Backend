import asyncio
from datetime import datetime, timezone
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

if "aiosqlite" not in sys.modules:
    import sqlite3 as _sqlite3

    stub = types.ModuleType("aiosqlite")

    async def _connect(*args, **kwargs):  # pragma: no cover - fallback only
        raise RuntimeError("aiosqlite is required for async database operations")

    stub.connect = _connect
    stub.paramstyle = "qmark"
    stub.sqlite_version = getattr(_sqlite3, "sqlite_version", "3.0.0")
    stub.sqlite_version_info = getattr(_sqlite3, "sqlite_version_info", (3, 0, 0))
    stub.DatabaseError = _sqlite3.DatabaseError
    stub.Error = _sqlite3.Error
    stub.IntegrityError = _sqlite3.IntegrityError
    stub.InterfaceError = getattr(_sqlite3, "InterfaceError", _sqlite3.Error)
    stub.OperationalError = _sqlite3.OperationalError
    stub.ProgrammingError = _sqlite3.ProgrammingError
    stub.NotSupportedError = getattr(_sqlite3, "NotSupportedError", _sqlite3.Error)
    stub.Warning = getattr(_sqlite3, "Warning", Exception)
    sys.modules["aiosqlite"] = stub

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.routes.auth import login, register
from app.routes.password_reset import ForgotPasswordIn, ResetPasswordIn, forgot_password, reset_password
from app.schemas import UserRegister
from app.models import competition, team, user  # noqa: F401
from app.models.user import User


class AsyncSessionWrapper:
    """Minimal async-compatible wrapper around a synchronous SQLAlchemy Session for testing."""

    def __init__(self, session: Session):
        self._session = session

    async def execute(self, *args, **kwargs):
        return self._session.execute(*args, **kwargs)

    def add(self, instance):
        self._session.add(instance)

    async def commit(self):
        self._session.commit()

    async def refresh(self, instance):
        self._session.refresh(instance)

    async def close(self):
        self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()


def create_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


async def call_with_session(factory, fn, *args, **kwargs):
    session = factory()
    wrapper = AsyncSessionWrapper(session)
    try:
        return await fn(*args, db=wrapper, **kwargs)
    finally:
        await wrapper.close()


async def _run_password_reset_flow():
    engine, session_factory = create_session_factory()

    try:
        await call_with_session(
            session_factory,
            register,
            UserRegister(
                username="testuser",
                email="user@example.com",
                password="initialPass1",
            ),
        )

        background = BackgroundTasks()

        class _NaiveDateTime:
            timezone = timezone

            @staticmethod
            def now(_tz=None):
                return datetime.now(timezone.utc)

        with patch("app.routes.password_reset.generate_reset_token", return_value="reset-token"), patch(
            "app.routes.password_reset.send_email", return_value=None
        ), patch("app.routes.password_reset.datetime", _NaiveDateTime):
            response = await call_with_session(
                session_factory,
                forgot_password,
                ForgotPasswordIn(email="user@example.com"),
                background,
            )
            assert response == {
                "ok": True,
                "message": "If that email exists, you’ll receive reset instructions.",
            }

            reset_response = await call_with_session(
                session_factory,
                reset_password,
                ResetPasswordIn(token="reset-token", new_password="newSecurePass2"),
            )
        assert reset_response == {"ok": True}

        login_response = await call_with_session(
            session_factory,
            login,
            SimpleNamespace(username="user@example.com", password="newSecurePass2"),
        )
        assert login_response["token_type"] == "bearer"
        assert "access_token" in login_response
    finally:
        engine.dispose()


def test_password_reset_allows_login():
    asyncio.run(_run_password_reset_flow())


async def _run_duplicate_username_registration():
    engine, session_factory = create_session_factory()

    try:
        await call_with_session(
            session_factory,
            register,
            UserRegister(
                username="testuser",
                email="user@example.com",
                password="initialPass1",
            ),
        )

        with pytest.raises(HTTPException) as excinfo:
            await call_with_session(
                session_factory,
                register,
                UserRegister(
                    username="testuser",
                    email="another@example.com",
                    password="anotherPass2",
                ),
            )

        assert excinfo.value.status_code == 400
        assert excinfo.value.detail == "Username already exists"
    finally:
        engine.dispose()


def test_register_rejects_duplicate_username():
    asyncio.run(_run_duplicate_username_registration())
