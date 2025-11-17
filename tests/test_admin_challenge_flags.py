import asyncio
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))


# ---------------------------------------------------------------------------
# Minimal stubs to avoid importing heavy async SQLAlchemy dependencies
# ---------------------------------------------------------------------------
if "app.database" not in sys.modules:
    fake_database = types.ModuleType("app.database")

    async def _fake_get_db():  # pragma: no cover - dependency placeholder
        yield None

    fake_database.get_db = _fake_get_db
    sys.modules["app.database"] = fake_database


def _install_model_stub(module_name: str, attrs: dict) -> None:
    module = types.ModuleType(module_name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[module_name] = module


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


_install_model_stub(
    "app.models.challenge",
    {
        "Challenge": _ChallengeStub,
    },
)
_install_model_stub("app.models.hint", {"Hint": _HintStub})
_install_model_stub("app.models.challenge_tag", {"ChallengeTag": _ChallengeTagStub})
_install_model_stub("app.models.submission", {"Submission": _SubmissionStub})
_install_model_stub("app.models.user", {"User": _UserStub})


from app.routes.admin_challenges import create_challenge  # noqa: E402
from app.routes.admin_challenges import _to_admin_schema  # noqa: E402
from app.flag_storage import hash_flag, verify_flag  # noqa: E402
from app.schemas import ChallengeCreate  # noqa: E402


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

        with patch("app.routes.admin_challenges.Challenge", _ChallengeStub), patch(
            "app.routes.admin_challenges._to_admin_schema",
            side_effect=lambda ch, solves: SimpleNamespace(id=ch.id, solves=solves),
        ), patch(
            "app.routes.admin_challenges._solves_count",
            new=AsyncMock(return_value=0),
        ) as solves_mock:
            result = await create_challenge(payload, session, None)

        solves_mock.assert_awaited_once()
        assert session.flush.await_count == 1
        assert session.commit.await_count == 1
        assert session.refresh.await_count == 1
        assert result.id == 1

        challenge = session.added[0]
        assert verify_flag(plain_flag, challenge.flag)
        assert challenge.flag != plain_flag

    asyncio.run(_run())


def test_admin_schema_exposes_stored_flag_hash():
    hashed = hash_flag("FLAG{secret}")
    challenge = _ChallengeStub(
        id=7,
        flag=hashed,
        title="Demo",
        description="",
        category_id=1,
        points=100,
        created_at=datetime.now(timezone.utc),
    )

    result = _to_admin_schema(challenge, solves=0)

    assert result.flag_hash == hashed
