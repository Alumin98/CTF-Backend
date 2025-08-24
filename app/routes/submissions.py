# app/routes/submissions.py
# Tailored to: submissions.is_correct TEXT ('true'/'false'), NO submissions.score column

from datetime import datetime
from typing import Optional, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, desc, asc, cast, Boolean

from app.database import get_db
from app.auth_token import get_current_user
from app.routes.auth import hash_flag

from app.models.submission import Submission
from app.models.challenge import Challenge
from app.models.user import User
from app.models.team import Team
from app.models.event_challenge import EventChallenge

from app.schemas import FlagSubmission, SubmissionResult

router = APIRouter()

# -------------------------------------------------------------------
# POST /submit  – record a submission (TEXT is_correct)
# -------------------------------------------------------------------
@router.post("/submit/", response_model=SubmissionResult)
async def submit_flag(
    submission: FlagSubmission,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
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
                cast(Submission.is_correct, Boolean) == True,  # CAST TEXT -> BOOL
            )
        )
        if solved_res.scalar_one_or_none():
            return {"correct": False, "message": "You already solved this challenge."}

        # 3) Check flag
        submitted_hash = hash_flag(submission.submitted_flag)
        is_correct_bool = (submitted_hash == challenge.flag)

        # 4) First blood?
        fb_res = await db.execute(
            select(Submission.id).where(
                Submission.challenge_id == challenge.id,
                cast(Submission.is_correct, Boolean) == True,
                Submission.first_blood == True,
            )
        )
        is_first_blood = False if fb_res.scalar_one_or_none() else True

        # 5) Save submission (store TEXT 'true'/'false' to match DB)
        new_sub = Submission(
            user_id=user.id,
            challenge_id=challenge.id,
            submitted_hash=submitted_hash,
            is_correct="true" if is_correct_bool else "false",
            submitted_at=datetime.utcnow(),
            first_blood=is_first_blood,
            # NOTE: do not set Submission.score — your DB doesn't have that column
        )
        db.add(new_sub)
        await db.commit()

        # Optional: dynamic score for UI only (not stored in DB)
        score_awarded = 0
        if is_correct_bool:
            # simple decreasing scheme, independent of DB schema
            n_res = await db.execute(
                select(func.count(func.distinct(User.team_id)))
                .select_from(Submission)
                .join(User, User.id == Submission.user_id)
                .where(
                    Submission.challenge_id == challenge.id,
                    cast(Submission.is_correct, Boolean) == True,
                    User.team_id.isnot(None),
                )
            )
            n_solves = n_res.scalar_one() or 0
            score_awarded = max(100 - (10 * n_solves), 10)

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
# GET /leaderboard  – sum Challenge.points for FIRST correct solves
#                     tie-break = earliest first_solve_at
#                     optional ?event_id= via event_challenges
# -------------------------------------------------------------------
@router.get("/leaderboard/")
async def get_leaderboard(
    db: AsyncSession = Depends(get_db),
    type: Literal["user", "team"] = "team",
    event_id: Optional[int] = None,
    limit: int = 100,
):
    IS_CORRECT_TRUE = cast(Submission.is_correct, Boolean) == True

    # Earliest correct submission per (user, challenge)
    first_correct = (
        select(
            Submission.user_id.label("user_id"),
            Submission.challenge_id.label("challenge_id"),
            func.min(Submission.submitted_at).label("first_solve_at"),
        )
        .where(IS_CORRECT_TRUE)
        .group_by(Submission.user_id, Submission.challenge_id)
        .cte("first_correct")
    )

    # Join to Challenge.points; optionally scope by event
    base_q = (
        select(
            first_correct.c.user_id,
            first_correct.c.challenge_id,
            first_correct.c.first_solve_at,
            Challenge.points.label("points"),
        )
        .join(Challenge, Challenge.id == first_correct.c.challenge_id)
    )

    if event_id is not None:
        base_q = (
            base_q.join(
                EventChallenge,
                EventChallenge.challenge_id == first_correct.c.challenge_id,
            )
            .where(EventChallenge.event_id == event_id)
        )

    fc_with_points = base_q.cte("fc_with_points")

    if type == "user":
        stmt = (
            select(
                User.id.label("subject_id"),
                func.coalesce(User.username, User.email, User.id).label("name"),
                func.coalesce(func.sum(fc_with_points.c.points), 0).label("score"),
                func.min(fc_with_points.c.first_solve_at).label("first_solve_at"),
            )
            .select_from(User)
            .join(fc_with_points, fc_with_points.c.user_id == User.id)
            .group_by(User.id, func.coalesce(User.username, User.email, User.id))
            .order_by(desc("score"), asc("first_solve_at"))
            .limit(limit)
        )
    else:
        stmt = (
            select(
                Team.id.label("subject_id"),
                Team.team_name.label("name"),  # your table uses team_name
                func.coalesce(func.sum(fc_with_points.c.points), 0).label("score"),
                func.min(fc_with_points.c.first_solve_at).label("first_solve_at"),
            )
            .select_from(Team)
            .join(User, User.team_id == Team.id)
            .join(fc_with_points, fc_with_points.c.user_id == User.id)
            .group_by(Team.id, Team.team_name)
            .order_by(desc("score"), asc("first_solve_at"))
            .limit(limit)
        )

    rows = (await db.execute(stmt)).all()

    # Rank with ties (score, first_solve_at)
    results, rank, prev_key = [], 0, None
    for r in rows:
        score = int(r.score or 0)
        ts = r.first_solve_at
        key = (score, ts)
        if key != prev_key:
            rank = len(results) + 1
            prev_key = key
        results.append(
            {
                "rank": rank,
                "subject_type": type,
                "subject_id": r.subject_id,
                "name": r.name,
                "score": score,
                "first_solve_at": ts.isoformat() if ts else None,
            }
        )

    return {"type": type, "event_id": event_id, "results": results}
