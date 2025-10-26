import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.routes.auth import update_profile
from app.schemas import UserProfileUpdate


class _FakeResult:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, existing=None):
        self._existing = existing
        self.commit_called = False

    async def execute(self, stmt):
        return _FakeResult(self._existing)

    def add(self, obj):
        pass

    async def commit(self):
        self.commit_called = True

    async def refresh(self, obj):
        return obj


def test_update_profile_changes_fields(monkeypatch):
    async def _run():
        user = SimpleNamespace(
            id=1,
            username="olduser",
            email="old@example.com",
            password_hash="hash",
            display_name=None,
            bio=None,
            created_at=datetime.utcnow(),
        )

        session = _FakeSession()
        payload = UserProfileUpdate(
            username="newuser",
            email="new@example.com",
            password="newpassword",
            display_name="Player One",
            bio="hello",
        )

        result = await update_profile(payload, current_user=user, db=session)

        assert result.username == "newuser"
        assert result.email == "new@example.com"
        assert result.display_name == "Player One"
        assert session.commit_called is True

    asyncio.run(_run())


def test_update_profile_rejects_short_password():
    async def _run():
        user = SimpleNamespace(
            id=1,
            username="user",
            email="user@example.com",
            password_hash="hash",
            display_name=None,
            bio=None,
            created_at=datetime.utcnow(),
        )
        session = _FakeSession()

        payload = UserProfileUpdate(password="123")

        with pytest.raises(Exception) as excinfo:
            await update_profile(payload, current_user=user, db=session)

        assert "Password too short" in str(excinfo.value)

    asyncio.run(_run())
