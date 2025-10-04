# app/routes/achievements.py
from __future__ import annotations
from datetime import datetime
import os
from typing import Optional, List

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, cast, Boolean, delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth_token import get_current_user, require_admin   # <-- use your real auth
from app.models.achievement import Achievement, AchievementType
from app.models.submission import Submission
from app.models.challenge import Challenge
from app.models.user import User
from app.schemas import AchievementRead

router = APIRouter(prefix="/achievements", tags=["Achievements"])


def _parse_iso8601(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


@router.get("/me", response_model=List[AchievementRead])
async def my_achievements(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),  # <-- auth enforced here
):
    rows = (
        await db.execute(
            select(Achievement)
            .where(Achievement.user_id == user.id)
            .order_by(Achievement.awarded_at.desc())
        )
    ).scalars().all()
    return rows


@router.get("/user/{user_id}", response_model=List[AchievementRead])
async def achievements_for_user(user_id: int, db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Achievement)
            .where(Achievement.user_id == user_id)
            .order_by(Achievement.awarded_at.desc())
        )
    ).scalars().all()
    return rows


@router.post("/recompute/category-king", response_model=dict)
async def recompute_category_king(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),  # <-- admin-only
    category_id: Optional[int] = Query(None),
    freeze_until: Optional[str] = Query(
        None,
        description="ISO-8601 UTC; ignore solves after this (anti-cheat freeze). "
        "If omitted, uses SCOREBOARD_FREEZE_AT env var if set.",
    ),
):
    freeze = _parse_iso8601(freeze_until) or _parse_iso8601(os.getenv("SCOREBOARD_FREEZE_AT"))
    IS_CORRECT_TRUE = cast(Submission.is_correct, Boolean) == True  # noqa: E712

    stmt = (
        select(
            Submission.user_id.label("user_id"),
            Challenge.category_id.label("category_id"),
            func.sum(Submission.points_awarded).label("score"),
            func.min(Submission.submitted_at).label("first_solve_at"),
        )
        .join(Challenge, Challenge.id == Submission.challenge_id)
        .where(IS_CORRECT_TRUE)
        .group_by(Submission.user_id, Challenge.category_id)
    )
    if freeze is not None:
        stmt = stmt.where(Submission.submitted_at <= freeze)
    if category_id is not None:
        stmt = stmt.where(Challenge.category_id == category_id)

    rows = (await db.execute(stmt)).all()
    if not rows:
        return {"updated": 0, "message": "No data"}

    # pick winners per category: max score, tie-break earliest first_solve_at
    by_cat = {}
    for r in rows:
        if r.category_id is None:
            continue
        current = by_cat.get(r.category_id)
        candidate_key = (int(r.score or 0), r.first_solve_at)
        if not current:
            by_cat[r.category_id] = (r.user_id, candidate_key)
        else:
            best_score, best_ts = current[1]
            if candidate_key[0] > best_score or (
                candidate_key[0] == best_score and (best_ts is None or (r.first_solve_at and r.first_solve_at < best_ts))
            ):
                by_cat[r.category_id] = (r.user_id, candidate_key)

    cat_ids = list(by_cat.keys())
    if cat_ids:
        await db.execute(
            delete(Achievement).where(
                Achievement.type == AchievementType.CATEGORY_KING,
                Achievement.category_id.in_(cat_ids),
            )
        )
        values = []
        for cid, (uid, (score, _ts)) in by_cat.items():
            values.append(
                dict(
                    user_id=uid,
                    type=AchievementType.CATEGORY_KING,
                    challenge_id=None,
                    category_id=cid,
                    details=f"Top scorer in category {cid}",
                    points_at_award=score,
                )
            )
        if values:
            await db.execute(insert(Achievement), values)
        await db.commit()

    return {"updated": len(by_cat), "categories": cat_ids}
