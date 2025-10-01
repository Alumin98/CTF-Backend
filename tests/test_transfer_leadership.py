import sys
import types
from pathlib import Path

# Provide a lightweight stub for the optional aiosqlite dependency used during imports.
fake_aiosqlite = types.ModuleType("aiosqlite")


class _FakeConnection:
    async def cursor(self):  # pragma: no cover - compatibility shim
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

from app.routes import teams  # noqa: E402  - imported after sys.path adjustment
from app.models.team import Team  # noqa: E402
from app.models.user import User  # noqa: E402


class SimpleUser:
    def __init__(self, user_id: int, role: str = "player", team_id: int | None = None):
        self.id = user_id
        self.role = role
        self.team_id = team_id


class SimpleTeam:
    def __init__(self, team_id: int, leader_id: int):
        self.id = team_id
        self.leader_id = leader_id


class FakeAsyncSession:
    def __init__(self, team: SimpleTeam, members: list[SimpleUser]):
        self._team = team
        self._members = {member.id: member for member in members}
        self.committed = False

    async def get(self, model, obj_id):
        if model is Team and obj_id == self._team.id:
            return self._team
        if model is User:
            return self._members.get(obj_id)
        return None

    async def commit(self):
        self.committed = True


def test_admin_can_transfer_leadership_without_being_current_leader():
    team = SimpleTeam(team_id=11, leader_id=22)
    admin_user = SimpleUser(user_id=99, role="admin")
    new_leader = SimpleUser(user_id=33, team_id=team.id)
    fake_session = FakeAsyncSession(team, members=[new_leader])

    async def _run_transfer():
        await teams.transfer_leadership(
            team_id=team.id,
            new_leader_user_id=new_leader.id,
            db=fake_session,
            current_user=admin_user,
        )

    import asyncio

    asyncio.run(_run_transfer())

    assert team.leader_id == new_leader.id
    assert fake_session.committed is True
