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

@router.get("/leaderboard/")
async def get_leaderboard(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            User.username,
            func.sum(Challenge.points).label("score")
        )
        .join(Submission, Submission.user_id == User.id)
        .join(Challenge, Challenge.id == Submission.challenge_id)
        .where(Submission.is_correct == True)
        .group_by(User.id, User.username)
        .order_by(func.sum(Challenge.points).desc())
    )
    leaderboard = [{"username": row[0], "score": row[1]} for row in result.all()]
    return leaderboard