from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.models.submission import Submission
from app.models.challenge import Challenge
from app.models.user import User
from app.schemas import FlagSubmission, SubmissionResult
from app.database import get_db
from app.auth_token import get_current_user
from app.routes.auth import hash_flag

router = APIRouter()

@router.post("/submit/", response_model=SubmissionResult)
async def submit_flag(
    submission: FlagSubmission,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    try:
        # Get challenge
        result = await db.execute(select(Challenge).where(Challenge.id == submission.challenge_id))
        challenge = result.scalar_one_or_none()
        if not challenge:
            raise HTTPException(status_code=404, detail="Challenge not found")

        # Check if already solved
        existing = await db.execute(
            select(Submission).where(
                Submission.user_id == user.id,
                Submission.challenge_id == submission.challenge_id,
                Submission.is_correct == True
            )
        )
        if existing.scalar_one_or_none():
            return {"correct": False, "message": "You already solved this challenge."}

        # Hash submitted flag and compare
        submitted_hash = hash_flag(submission.submitted_flag)
        is_correct = submitted_hash == challenge.flag
        
        score = 0
        if is_correct:
            # --- DYNAMIC SCORING LOGIC ---
            solved_teams_query = await db.execute(
                select(func.count(func.distinct(User.team_id)))
                .select_from(Submission)
                .join(User, Submission.user_id == User.id)
                .where(
                    Submission.challenge_id == challenge.id,
                    Submission.is_correct == True,
                    User.team_id != None
                )
            )
            number_of_solves = solved_teams_query.scalar_one() or 0
            score = max(100 - (10 * number_of_solves), 10)

        # Check if first blood exists for this challenge
        first_blood_exists = await db.execute(
            select(Submission).where(
            Submission.challenge_id == challenge.id,
            Submission.is_correct == True,
            Submission.first_blood == True
            )
        )
        is_first_blood = False if first_blood_exists.scalar_one_or_none() else True

        new_sub = Submission(
            user_id=user.id,
            challenge_id=challenge.id,
            submitted_hash=submitted_hash,
            is_correct=is_correct,
            submitted_at=datetime.utcnow(),
            first_blood=is_first_blood,
            score=score if is_correct else 0
        )
        db.add(new_sub)
        await db.commit()
        # Optionally: await db.refresh(new_sub)

        return {
            "correct": is_correct,
            "message": "Correct!" if is_correct else "Incorrect flag.",
            "score": score
        }

    except Exception as e:
        import logging
        logging.exception("Submission error")
        raise HTTPException(status_code=500, detail="Internal server error")

# --- REPLACE your existing /leaderboard/ with this ---

from typing import Optional, Literal
from sqlalchemy import desc, asc
from app.models.team import Team
from app.models.event_challenge import EventChallenge

@router.get("/leaderboard/")
async def get_leaderboard(
    db: AsyncSession = Depends(get_db),
    type: Literal["user","team"] = "team",
    event_id: Optional[int] = None,
    limit: int = 100
):
    """
    Ranks users or teams by total points with a tie-breaker on earliest correct submission.
    Optional event filter via EventChallenge mapping.
    """
    # Base: only correct submissions (your model stores 'true'/'false' as strings)
    base = (
        select(Submission, User, Challenge)
        .join(User, User.id == Submission.user_id)
        .join(Challenge, Challenge.id == Submission.challenge_id)
        .where(Submission.is_correct == 'true')
    )

    # Event filter via EventChallenge (Submission doesn't have event_id)
    if event_id is not None:
        base = (
            base.join(EventChallenge, EventChallenge.challenge_id == Submission.challenge_id)
                .where(EventChallenge.event_id == event_id)
        )

    if type == "user":
        # Aggregate by user
        stmt = (
            select(
                User.id.label("subject_id"),
                User.username.label("name"),
                func.coalesce(func.sum(Challenge.points), 0).label("score"),
                func.min(Submission.submitted_at).label("first_solve_at"),
            )
            .select_from(base.subquery())
            .group_by(User.id, User.username)
            .order_by(desc("score"), asc("first_solve_at"))
            .limit(limit)
        )
    else:
        # Aggregate by team (uses users.team_id per your current schema)
        stmt = (
            select(
                Team.id.label("subject_id"),
                Team.team_name.label("name"),
                func.coalesce(func.sum(Challenge.points), 0).label("score"),
                func.min(Submission.submitted_at).label("first_solve_at"),
            )
            .select_from(base.join(Team, Team.id == User.team_id).subquery())
            .group_by(Team.id, Team.team_name)
            .order_by(desc("score"), asc("first_solve_at"))
            .limit(limit)
        )

    rows = (await db.execute(stmt)).all()

    # Assign ranks with ties on (score, first_solve_at)
    results = []
    rank = 0
    prev_key = None
    for r in rows:
        score = int(r.score or 0)
        ts = r.first_solve_at
        key = (score, ts)
        if key != prev_key:
            rank = len(results) + 1
            prev_key = key
        results.append({
            "rank": rank,
            "subject_type": type,
            "subject_id": r.subject_id,
            "name": r.name,
            "score": score,
            "first_solve_at": ts.isoformat() if ts else None
        })

    return {"type": type, "event_id": event_id, "results": results}
