import sys
import types
from pathlib import Path
from unittest.mock import patch

# Provide a lightweight stub for the optional aiosqlite dependency used during imports.
fake_aiosqlite = types.ModuleType("aiosqlite")


class _FakeConnection:
    async def cursor(self):  # pragma: no cover - unused but kept for compatibility
        return self

    async def execute(self, *args, **kwargs):  # noqa: ARG002 - compat shim
        return None

    async def fetchone(self):
        return None

    async def fetchall(self):
        return []

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def close(self):
        return None


async def _fake_connect(*args, **kwargs):  # noqa: ARG001 - compatibility shim
    return _FakeConnection()


fake_aiosqlite.connect = _fake_connect
fake_aiosqlite.Error = Exception
fake_aiosqlite.Warning = Exception
fake_aiosqlite.DatabaseError = Exception
fake_aiosqlite.IntegrityError = Exception
fake_aiosqlite.ProgrammingError = Exception
fake_aiosqlite.OperationalError = Exception
fake_aiosqlite.InterfaceError = Exception
fake_aiosqlite.InternalError = Exception
fake_aiosqlite.NotSupportedError = Exception
fake_aiosqlite.DataError = Exception
fake_aiosqlite.apilevel = "2.0"
fake_aiosqlite.threadsafety = 1
fake_aiosqlite.paramstyle = "qmark"
fake_aiosqlite.sqlite_version = "3.0.0"
fake_aiosqlite.sqlite_version_info = (3, 0, 0)
fake_aiosqlite.version = "0.0"
fake_aiosqlite.version_info = (0, 0, 0)
sys.modules.setdefault("aiosqlite", fake_aiosqlite)

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.routes import teams


class FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class FakeResult:
    def __init__(self, value=None, scalars=None):
        self._value = value
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return FakeScalarResult(self._scalars)


class FakeAsyncSession:
    def __init__(self, team, members=None):
        self._team = team
        self._members = members or []
        self._execute_calls = 0
        self.added = []
        self.committed = False

    async def execute(self, stmt):  # noqa: ARG002 - stmt unused beyond call order
        self._execute_calls += 1
        if self._execute_calls == 1:
            return FakeResult(value=self._team)
        return FakeResult(value=None, scalars=self._members)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):  # noqa: ARG002 - refresh is a no-op for the fake session
        return None


class SimpleUser:
    def __init__(self, user_id: int, role: str = "admin"):
        self.id = user_id
        self.role = role


class SimpleTeam:
    def __init__(self, team_id: int, created_by: int, team_name: str):
        self.id = team_id
        self.created_by = created_by
        self.team_name = team_name
        self.leader_id = created_by
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by_user_id = None


def test_delete_team_sets_deleted_by_user_id():
    user = SimpleUser(user_id=5, role="admin")
    team = SimpleTeam(team_id=7, created_by=user.id, team_name="team-to-delete")
    fake_session = FakeAsyncSession(team)

    async def _run_delete():
        with patch.object(teams, "team_has_participated", return_value=False):
            await teams.delete_team(team_id=team.id, db=fake_session, user=user)

    import asyncio

    asyncio.run(_run_delete())

    assert team.is_deleted is True
    assert team.deleted_by_user_id == user.id
    assert fake_session.committed is True
