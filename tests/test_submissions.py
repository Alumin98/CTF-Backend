import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

aiosqlite_stub_path = ROOT / "tests" / "aiosqlite_stub.py"
spec = importlib.util.spec_from_file_location("aiosqlite", aiosqlite_stub_path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
sys.modules.setdefault("aiosqlite", module)

from app.database import Base
from app.models import (
    activity_log as _activity_log_model,  # noqa: F401 (imported for side effects)
    admin_action as _admin_action_model,  # noqa: F401
    category as _category_model,  # noqa: F401
    challenge as _challenge_model,  # noqa: F401
    challenge_tag as _challenge_tag_model,  # noqa: F401
    competition as _competition_model,  # noqa: F401
    event as _event_model,  # noqa: F401
    event_challenge as _event_challenge_model,  # noqa: F401
    hint as _hint_model,  # noqa: F401
    role as _role_model,  # noqa: F401
    submission as _submission_model,  # noqa: F401
    team as _team_model,  # noqa: F401
    team_member as _team_member_model,  # noqa: F401
    user as _user_model,  # noqa: F401
)
from app.models.challenge import Challenge
from app.models.submission import Submission
from app.models.user import User
from app.routes.auth import hash_flag
from app.routes.submissions import get_leaderboard, submit_flag
from app.schemas import FlagSubmission


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_correct_submission_scores_and_persists(tmp_path):
    """A correct submission should award a positive score and store it for aggregation."""

    db_file = tmp_path / "submissions.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        user = User(
            username="player1",
            email="player1@example.com",
            password_hash="not-used-in-test",
        )
        challenge = Challenge(
            title="Warmup",
            description="Test challenge",
            flag=hash_flag("flag{warmup}"),
            points=100,
        )
        session.add_all([user, challenge])
        await session.commit()
        await session.refresh(user)
        await session.refresh(challenge)

        payload = FlagSubmission(
            challenge_id=challenge.id,
            submitted_flag="flag{warmup}",
            used_hint_ids=[],
        )

        result = await submit_flag(submission=payload, db=session, user=user)

        assert result["correct"] is True
        assert result["score"] > 0

        user_id = user.id
        challenge_id = challenge.id

    async with async_session() as verify_session:
        stored_submission = (
            await verify_session.execute(
                select(Submission).where(
                    Submission.user_id == user_id,
                    Submission.challenge_id == challenge_id,
                )
            )
        ).scalar_one()

        assert stored_submission.points_awarded == result["score"]
        assert stored_submission.points_awarded > 0

        leaderboard = await get_leaderboard(db=verify_session, type="user")
        matching_entries = [
            entry for entry in leaderboard["results"] if entry["subject_id"] == user_id
        ]

        assert matching_entries, "Leaderboard should include the scoring user"
        assert matching_entries[0]["score"] == result["score"]

    await engine.dispose()
