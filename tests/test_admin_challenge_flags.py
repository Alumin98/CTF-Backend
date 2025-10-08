import asyncio
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# Provide a lightweight stub for the optional aiosqlite dependency so the real
# ``app.database`` module can be imported without pulling in heavy async
# dependencies during test collection.
# ---------------------------------------------------------------------------
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


def _fake_connect(*args, **kwargs):  # noqa: ARG001 - compatibility shim
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from app.routes.auth import hash_flag  # noqa: E402
from app.schemas import ChallengeCreate  # noqa: E402


class _ChallengeStub:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id")
        self.title = kwargs.get("title")
        self.description = kwargs.get("description")
        self.category_id = kwargs.get("category_id")
        self.points = kwargs.get("points")
        self.difficulty = kwargs.get("difficulty")
        self.docker_image = kwargs.get("docker_image")
        self.is_active = kwargs.get("is_active")
        self.is_private = kwargs.get("is_private")
        self.visible_from = kwargs.get("visible_from")
        self.visible_to = kwargs.get("visible_to")
        self.competition_id = kwargs.get("competition_id")
        self.unlocked_by_id = kwargs.get("unlocked_by_id")
        self.flag = kwargs.get("flag")
        self.created_at = kwargs.get("created_at")
        self.hints = []
        self._tag_strings = []

    @property
    def tag_strings(self):
        return list(self._tag_strings)

    def set_tag_strings(self, items):
        self._tag_strings = list(items or [])


class _HintStub:
    def __init__(self, text, penalty=0, order_index=0):
        self.text = text
        self.penalty = penalty
        self.order_index = order_index


class _ChallengeTagStub:
    def __init__(self, tag):
        self.tag = tag


class _SubmissionStub:
    id = 1


class _UserStub:
    def __init__(self, is_admin=True, is_superuser=False):
        self.is_admin = is_admin
        self.is_superuser = is_superuser


def _install_model_stub(module_name: str, attrs: dict):
    previous = sys.modules.get(module_name)
    module = types.ModuleType(module_name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[module_name] = module
    return previous


def _restore_modules(originals: dict[str, types.ModuleType | None]) -> None:
    for name, previous in originals.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


class _FakeResult:
    def scalar_one(self):
        return 0


class _FakeSession:
    def __init__(self):
        self.added = []
        self.flush = AsyncMock(side_effect=self._assign_ids)
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.execute = AsyncMock(return_value=_FakeResult())

    def add(self, obj):
        self.added.append(obj)

    async def _assign_ids(self):
        for idx, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                obj.id = idx


def test_new_challenge_stores_hashed_flag():
    async def _run():
        session = _FakeSession()

        plain_flag = "FLAG{hash-me}"
        payload = ChallengeCreate(
            title="Hashing Test",
            description="Ensure flags are stored hashed",
            category_id=1,
            points=100,
            flag=plain_flag,
        )

        originals = {
            "app.models.challenge": _install_model_stub(
                "app.models.challenge",
                {
                    "Challenge": _ChallengeStub,
                },
            ),
            "app.models.hint": _install_model_stub(
                "app.models.hint",
                {
                    "Hint": _HintStub,
                },
            ),
            "app.models.challenge_tag": _install_model_stub(
                "app.models.challenge_tag",
                {
                    "ChallengeTag": _ChallengeTagStub,
                },
            ),
            "app.models.submission": _install_model_stub(
                "app.models.submission",
                {
                    "Submission": _SubmissionStub,
                },
            ),
            "app.models.user": _install_model_stub(
                "app.models.user",
                {
                    "User": _UserStub,
                },
            ),
        }

        solves_mock = None
        try:
            admin_module = importlib.import_module("app.routes.admin_challenges")

            with patch.object(admin_module, "Challenge", _ChallengeStub), patch.object(
                admin_module,
                "_to_admin_schema",
                side_effect=lambda ch, solves: SimpleNamespace(id=ch.id, solves=solves),
            ), patch.object(
                admin_module,
                "_solves_count",
                new=AsyncMock(return_value=0),
            ) as solves_mock:
                result = await admin_module.create_challenge(payload, session, None)
        finally:
            sys.modules.pop("app.routes.admin_challenges", None)
            _restore_modules(originals)

        assert solves_mock is not None
        solves_mock.assert_awaited_once()
        assert session.flush.await_count == 1
        assert session.commit.await_count == 1
        assert session.refresh.await_count == 1
        assert result.id == 1

        challenge = session.added[0]
        assert challenge.flag == hash_flag(plain_flag)
        assert challenge.flag != plain_flag

    asyncio.run(_run())
