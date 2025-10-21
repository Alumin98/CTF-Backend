# app/routes/scoreboard.py
from __future__ import annotations
import os
from datetime import datetime
from typing import Optional, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Boolean, Text, cast, desc, asc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.submission import Submission
from app.models.challenge import Challenge
from app.models.user import User
from app.models.team import Team
# If you later want event-scoped scoreboards, you can also import EventChallenge.

router = APIRouter(prefix="/scoreboard", tags=["Scoreboard"])


# --------- helpers ---------
def _parse_iso8601(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Accept 'Z' suffix
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _rank_rows(rows):
    ranked, prev_key, rank = [], None, 0
    for r in rows:
        key = (r["score"], r["first_solve_at"])
        if key != prev_key:
            rank = len(ranked) + 1
            prev_key = key
        ranked.append({**r, "rank": rank})
    return ranked


# --------- GET /scoreboard ---------
@router.get("")
async def get_scoreboard(
    db: AsyncSession = Depends(get_db),
    type: Literal["user", "team"] = Query("team", description="Aggregate by 'user' or 'team'"),
    limit: int = Query(100, ge=1, le=1000),
    category_id: Optional[int] = Query(None, description="Filter to a category"),
    challenge_id: Optional[int] = Query(None, description="Filter to a single challenge"),
    freeze_until: Optional[str] = Query(
        None,
        description="ISO-8601 timestamp (UTC) — hides solves after this time (anti-cheat freeze). "
                    "If omitted, will use SCOREBOARD_FREEZE_AT env var if set.",
    ),
):
    """
    Global scoreboard:
      - Sums *awarded* points from first correct solves.
      - Tie-breaker: earliest first_solve_at.
      - Filters: category or challenge.
      - Anti-cheat freeze: exclude solves after 'freeze_until'.
    """
    # Resolve freeze timestamp
    freeze = _parse_iso8601(freeze_until) or _parse_iso8601(os.getenv("SCOREBOARD_FREEZE_AT"))

    IS_CORRECT_TRUE = cast(Submission.is_correct, Boolean) == True  # noqa: E712

    # Base FROM + WHERE
    base = select(
        Submission.user_id.label("user_id"),
        Submission.challenge_id.label("challenge_id"),
        func.min(Submission.submitted_at).label("first_solve_at"),
        # If duplicates existed, the earliest correct is what counts — points_awarded on that row.
        # Using MAX is safe because duplicates (if any) will have 0 or same points.
        func.max(Submission.points_awarded).label("points"),
    ).where(IS_CORRECT_TRUE)

    if freeze is not None:
        base = base.where(Submission.submitted_at <= freeze)

    if challenge_id is not None:
        base = base.where(Submission.challenge_id == challenge_id)

    if category_id is not None:
        # Need the Challenge table to filter by category
        base = base.join(Challenge, Challenge.id == Submission.challenge_id).where(
            Challenge.category_id == category_id
        )
    else:
        # ensure FROM is set explicitly to Submission when no join used
        base = base.select_from(Submission)

    first_correct = base.group_by(Submission.user_id, Submission.challenge_id).cte("first_correct")

    results = []
    if type == "user":
        name_expr = func.coalesce(User.username, User.email, cast(User.id, Text))
        stmt = (
            select(
                User.id.label("subject_id"),
                name_expr.label("name"),
                func.coalesce(func.sum(first_correct.c.points), 0).label("score"),
                func.min(first_correct.c.first_solve_at).label("first_solve_at"),
            )
            .join(first_correct, first_correct.c.user_id == User.id)
            .group_by(User.id, name_expr)
            .order_by(desc("score"), asc("first_solve_at"))
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
        for r in rows:
            results.append(
                {
                    "subject_type": "user",
                    "subject_id": r.subject_id,
                    "name": r.name,
                    "score": int(r.score or 0),
                    "first_solve_at": r.first_solve_at.isoformat() if r.first_solve_at else None,
                }
            )
    else:  # team
        # Join users to teams then aggregate
        stmt = (
            select(
                Team.id.label("subject_id"),
                Team.team_name.label("name"),
                func.coalesce(func.sum(first_correct.c.points), 0).label("score"),
                func.min(first_correct.c.first_solve_at).label("first_solve_at"),
            )
            .join(User, User.team_id == Team.id)
            .join(first_correct, first_correct.c.user_id == User.id)
            .group_by(Team.id, Team.team_name)
            .order_by(desc("score"), asc("first_solve_at"))
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
        for r in rows:
            results.append(
                {
                    "subject_type": "team",
                    "subject_id": r.subject_id,
                    "name": r.name,
                    "score": int(r.score or 0),
                    "first_solve_at": r.first_solve_at.isoformat() if r.first_solve_at else None,
                }
            )

    # Rank with ties (score desc, first_solve asc)
    results.sort(key=lambda x: (-x["score"], x["first_solve_at"] or datetime.max.isoformat()))
    ranked = _rank_rows(results)

    return {
        "type": type,
        "category_id": category_id,
        "challenge_id": challenge_id,
        "freeze_until": freeze.isoformat() if freeze else None,
        "results": ranked,
    }
