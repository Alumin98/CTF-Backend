# app/routes/submissions.py

from datetime import datetime
import hashlib
import os
import hashlib
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, asc, cast, Boolean, insert

from app.database import get_db
from app.auth_token import get_current_user
from app.flag_storage import verify_flag
from app.rate_limiter import get_submission_rate_limiter

from app.models.submission import Submission
from app.models.challenge import Challenge
from app.models.hint import Hint
from app.models.user import User
from app.models.team import Team
from app.models.event_challenge import EventChallenge
from app.models.achievement import Achievement, AchievementType  # <-- NEW

from app.schemas import FlagSubmission, SubmissionResult

router = APIRouter()


# -------------------------------------------------------------------
# Scoring helpers (inlined here)
# -------------------------------------------------------------------
def dynamic_points(base: int, min_points: int, decay: int, current_solves: int) -> int:
    """
    Linear decay scoring:
    - Start from base points
    - Subtract decay * number of solves
    - Clamp to min_points
    """
    pts = base - (current_solves * decay)
    return max(min_points, pts)


def apply_hint_penalty(points: int, penalties: list[int]) -> int:
    """
    Deduct hint penalties from score.
    Never go below zero.
    """
    total_penalty = sum(penalties)
    return max(0, points - total_penalty)


# -------------------------------------------------------------------
# POST /submit – record a submission (+ achievements)
# -------------------------------------------------------------------
@router.post("/submit/", response_model=SubmissionResult)
async def submit_flag(
    submission: FlagSubmission,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        limiter = get_submission_rate_limiter()
        if limiter and not await limiter.try_acquire(f"user:{user.id}"):
            raise HTTPException(status_code=429, detail="Too many submissions. Please slow down.")

        # 1) Challenge must exist
        ch_res = await db.execute(
            select(Challenge).where(Challenge.id == submission.challenge_id)
        )
        challenge = ch_res.scalar_one_or_none()
        if not challenge:
            raise HTTPException(status_code=404, detail="Challenge not found")

        # 2) Already solved by this user?
        solved_res = await db.execute(
            select(Submission.id).where(
                Submission.user_id == user.id,
                Submission.challenge_id == submission.challenge_id,
                cast(Submission.is_correct, Boolean) == True,
            )
        )
        if solved_res.scalar_one_or_none():
            return {
                "correct": False,
                "message": "You already solved this challenge.",
                "score": 0,
            }

        # 3) Check flag
        submitted_hash = hashlib.sha256(submission.submitted_flag.encode("utf-8")).hexdigest()
        is_correct_bool = verify_flag(submission.submitted_flag, challenge.flag)

        # 4) First blood? (before inserting ours)
        fb_res = await db.execute(
            select(Submission.id).where(
                Submission.challenge_id == challenge.id,
                cast(Submission.is_correct, Boolean) == True,
                Submission.first_blood == True,
            )
        )
        is_first_blood = False if fb_res.scalar_one_or_none() else True

        # 5) Calculate score ahead of time so we can persist it
        score_awarded = 0
        if is_correct_bool:
            # count current correct solves (BEFORE this one)
            n_res = await db.execute(
                select(func.count(Submission.id)).where(
                    Submission.challenge_id == challenge.id,
                    cast(Submission.is_correct, Boolean) == True,
                )
            )
            n_solves = n_res.scalar_one() or 0

            # base dynamic points
            base = challenge.points or 100  # fallback if challenge.points is NULL
            min_points = 10
            decay = 10
            points = dynamic_points(base, min_points, decay, n_solves)

            # apply hint penalties
            penalties = []
            if submission.used_hint_ids:
                hint_rows = (
                    await db.execute(select(Hint).where(Hint.id.in_(submission.used_hint_ids)))
                ).scalars().all()
                penalties = [h.penalty for h in hint_rows]

            score_awarded = apply_hint_penalty(points, penalties)

        # 6) Save submission (TEXT 'true'/'false' in DB)
        new_sub = Submission(
            user_id=user.id,
            challenge_id=challenge.id,
            submitted_hash=submitted_hash,
            is_correct="true" if is_correct_bool else "false",
            submitted_at=datetime.utcnow(),
            first_blood=is_first_blood,
            points_awarded=score_awarded if is_correct_bool else 0,
            used_hint_ids=",".join(map(str, submission.used_hint_ids)) if submission.used_hint_ids else None,
        )
        db.add(new_sub)
        await db.commit()

        # 7) Achievements (best-effort; ignore unique errors)
        if is_correct_bool:
            # FIRST BLOOD
            if is_first_blood:
                try:
                    await db.execute(
                        insert(Achievement).values(
                            user_id=user.id,
                            type=AchievementType.FIRST_BLOOD,
                            challenge_id=challenge.id,
                            category_id=None,
                            details="First correct solver",
                            points_at_award=score_awarded,
                        )
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()

            # FAST SOLVER (within N minutes of visible_from)
            fast_minutes = int(os.getenv("FAST_SOLVER_MINUTES", "10"))
            if challenge.visible_from:
                delta = new_sub.submitted_at - challenge.visible_from
                if delta.total_seconds() <= fast_minutes * 60:
                    try:
                        await db.execute(
                            insert(Achievement).values(
                                user_id=user.id,
                                type=AchievementType.FAST_SOLVER,
                                challenge_id=challenge.id,
                                category_id=challenge.category_id,
                                details=f"Solved within {fast_minutes} minutes",
                                points_at_award=score_awarded,
                            )
                        )
                        await db.commit()
                    except Exception:
                        await db.rollback()

        return {
            "correct": is_correct_bool,
            "message": "Correct!" if is_correct_bool else "Incorrect flag.",
            "score": score_awarded,
        }

    except Exception:
        import logging
        logging.exception("Submission error")
        raise HTTPException(status_code=500, detail="Internal server error")


# -------------------------------------------------------------------
# GET /leaderboard – aggregate *awarded* scores (dynamic + penalties)
# -------------------------------------------------------------------
@router.get("/leaderboard/")
async def get_leaderboard(
    db: AsyncSession = Depends(get_db),
    type: Literal["user", "team"] = "team",
    event_id: Optional[int] = None,
    limit: int = 100,
):
    IS_CORRECT_TRUE = cast(Submission.is_correct, Boolean) == True

    # Use stored points_awarded, grouped by user (your /submit prevents duplicates per challenge)
    base_q = (
        select(
            Submission.user_id,
            func.min(Submission.submitted_at).label("first_solve_at"),
            func.sum(Submission.points_awarded).label("points"),
        )
        .where(IS_CORRECT_TRUE)
        .group_by(Submission.user_id)
    )

    # Scope by event if needed
    if event_id is not None:
        base_q = (
            base_q.join(EventChallenge, EventChallenge.challenge_id == Submission.challenge_id)
            .where(EventChallenge.event_id == event_id)
        )

    rows = (await db.execute(base_q)).all()

    user_ids = {r.user_id for r in rows}
    users = (
        await db.execute(select(User).where(User.id.in_(user_ids)))
        if user_ids
        else None
    )
    user_map = {u.id: u for u in (users.scalars().all() if users else [])}

    results = []
    if type == "user":
        for r in rows:
            u = user_map.get(r.user_id)
            results.append(
                {
                    "subject_type": "user",
                    "subject_id": r.user_id,
                    "name": u.username if u else f"User {r.user_id}",
                    "score": int(r.points or 0),
                    "first_solve_at": r.first_solve_at,
                }
            )
    else:  # team
        team_totals: dict[int, dict] = {}
        for r in rows:
            u = user_map.get(r.user_id)
            if not u or not u.team_id:
                continue

            team_entry = team_totals.setdefault(
                u.team_id,
                {
                    "subject_type": "team",
                    "subject_id": u.team_id,
                    "name": None,
                    "score": 0,
                    "first_solve_at": None,
                },
            )

            team_entry["score"] += int(r.points or 0)
            if r.first_solve_at:
                if not team_entry["first_solve_at"] or r.first_solve_at < team_entry["first_solve_at"]:
                    team_entry["first_solve_at"] = r.first_solve_at

        team_ids = list(team_totals.keys())
        teams = (
            await db.execute(select(Team).where(Team.id.in_(team_ids)))
            if team_ids
            else None
        )
        team_map = {t.id: t for t in (teams.scalars().all() if teams else [])}

        for team_id, entry in team_totals.items():
            team = team_map.get(team_id)
            entry["name"] = team.team_name if team else f"Team {team_id}"
            results.append(entry)

    # Rank results (score desc, tiebreak earliest solve)
    results.sort(key=lambda x: (-x["score"], x["first_solve_at"] or datetime.max))
    ranked, prev_key, rank = [], None, 0
    for r in results:
        key = (r["score"], r["first_solve_at"])
        if key != prev_key:
            rank = len(ranked) + 1
            prev_key = key
        first_solve = r["first_solve_at"]
        if isinstance(first_solve, datetime):
            first_solve = first_solve.isoformat()
        ranked.append({**r, "first_solve_at": first_solve, "rank": rank})

    return {"type": type, "event_id": event_id, "results": ranked[:limit]}
