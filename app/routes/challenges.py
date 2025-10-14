from datetime import datetime, timezone
from typing import List, Optional
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, cast, Boolean  # <-- added cast, Boolean
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth_token import get_current_user  # require auth to view challenges
from app.models.challenge import Challenge
from app.models.challenge_tag import ChallengeTag
from app.models.hint import Hint
from app.models.submission import Submission
from app.models.user import User
from app.models.team import Team
from app.schemas import ChallengePublic

router = APIRouter(prefix="/challenges", tags=["Challenges"])


# -----------------------------
# Helpers
# -----------------------------
async def _solves_count(db: AsyncSession, challenge_id: int) -> int:
    # Your DB stores is_correct as TEXT ('true'/'false'); cast to Boolean for correctness.
    q = select(func.count(Submission.id)).where(
        Submission.challenge_id == challenge_id,
        cast(Submission.is_correct, Boolean) == True,  # noqa: E712
    )
    return (await db.execute(q)).scalar_one() or 0


def _to_public_schema(ch: Challenge, solves: int) -> ChallengePublic:
    # Ensure hints are ordered for UI
    hints_sorted: List[Hint] = sorted(ch.hints or [], key=lambda h: h.order_index)
    return ChallengePublic(
        id=ch.id,
        title=ch.title,
        description=ch.description or "",
        category_id=ch.category_id,
        points=ch.points or 0,
        difficulty=ch.difficulty,
        created_at=ch.created_at,
        competition_id=ch.competition_id,
        unlocked_by_id=ch.unlocked_by_id,
        is_active=bool(ch.is_active),
        is_private=bool(ch.is_private),
        visible_from=ch.visible_from,
        visible_to=ch.visible_to,
        tags=ch.tag_strings,
        hints=hints_sorted,
        solves_count=solves,
    )


def _to_aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_iso8601(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


# -----------------------------
# Public endpoints
# -----------------------------
@router.get("", response_model=List[ChallengePublic])
async def list_challenges(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    category_id: Optional[int] = Query(None),
    difficulty: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    active_only: bool = True,
    respect_time_window: bool = True,
):
    """
    List challenges (public view).
    - Filter by category_id, difficulty, tag.
    - `active_only=True` hides inactive items.
    - `respect_time_window=True` enforces visible_from/visible_to against current time.
    """
    stmt = select(Challenge).order_by(Challenge.created_at.desc())

    if active_only:
        stmt = stmt.where(Challenge.is_active == True)  # noqa: E712
    if category_id is not None:
        stmt = stmt.where(Challenge.category_id == category_id)
    if difficulty:
        stmt = stmt.where(Challenge.difficulty == difficulty)
    if tag:
        stmt = stmt.join(ChallengeTag).where(ChallengeTag.tag == tag)

    rows: List[Challenge] = (await db.execute(stmt)).scalars().unique().all()

    # Time window filtering
    now = datetime.now(timezone.utc) if respect_time_window else None
    visible: List[Challenge] = []
    for c in rows:
        if not respect_time_window:
            visible.append(c)
            continue

        st = _to_aware(c.visible_from)
        et = _to_aware(c.visible_to)

        if st and now < st:
            continue
        if et and now > et:
            continue
        visible.append(c)

    # Build output with solves count
    out: List[ChallengePublic] = []
    for ch in visible:
        solves = await _solves_count(db, ch.id)
        out.append(_to_public_schema(ch, solves))
    return out


@router.get("/{challenge_id}", response_model=ChallengePublic)
async def get_challenge(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Get a single challenge (public view).
    Hides inactive/hidden challenges with a generic 404.
    """
    ch = await db.get(Challenge, challenge_id)
    if not ch or not ch.is_active:
        raise HTTPException(status_code=404, detail="Challenge not found")

    # Respect visibility window
    now = datetime.now(timezone.utc)
    st = _to_aware(ch.visible_from)
    et = _to_aware(ch.visible_to)
    if (st and now < st) or (et and now > et):
        raise HTTPException(status_code=404, detail="Challenge not found")

    solves = await _solves_count(db, ch.id)
    return _to_public_schema(ch, solves)


@router.get("/{challenge_id}/solvers")
async def get_challenge_solvers(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
    freeze_until: Optional[str] = Query(
        None,
        description="Anti-cheat: ISO-8601 UTC timestamp. Solves after this are hidden. "
                    "If omitted, uses SCOREBOARD_FREEZE_AT env var if set.",
    ),
):
    """
    List solvers for a challenge in solve order (first blood first).
    Anti-cheat: hide solves after the freeze time if provided.
    """
    freeze = _parse_iso8601(freeze_until) or _parse_iso8601(os.getenv("SCOREBOARD_FREEZE_AT"))

    stmt = (
        select(Submission, User, Team)
        .join(User, Submission.user_id == User.id)
        .join(Team, User.team_id == Team.id, isouter=True)
        .where(
            Submission.challenge_id == challenge_id,
            cast(Submission.is_correct, Boolean) == True,  # noqa: E712
        )
        .order_by(Submission.submitted_at.asc())
    )

    if freeze is not None:
        stmt = stmt.where(Submission.submitted_at <= freeze)

    rows = (await db.execute(stmt)).all()

    # mark first_blood on the earliest correct submission, if any (within freeze window if applied)
    first_blood_seen = False
    out = []
    for submission, user, team in rows:
        first_blood = False
        if not first_blood_seen:
            first_blood = True
            first_blood_seen = True

        out.append(
            {
                "team": team.team_name if team else None,
                "user": user.username,
                "timestamp": submission.submitted_at.isoformat(),
                "first_blood": first_blood,
                "points_awarded": submission.points_awarded or 0,
                "used_hint_ids": submission.used_hint_ids.split(",") if submission.used_hint_ids else [],
            }
        )
    return out
