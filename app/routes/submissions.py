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
        result = db.execute(select(Challenge).where(Challenge.id == submission.challenge_id))
        challenge = result.scalar()
        if not challenge:
            raise HTTPException(status_code=404, detail="Challenge not found")

        existing = db.execute(
            select(Submission).where(
                Submission.user_id == user.id,
                Submission.challenge_id == submission.challenge_id,
                Submission.is_correct == 'true'
            )
        )
        if existing.scalar():
            return {"correct": False, "message": "You already solved this challenge."}

        is_correct = submission.submitted_flag.strip() == challenge.flag.strip()

        new_sub = Submission(
            user_id=user.id,
            challenge_id=challenge.id,
            submitted_hash = hash_flag(submission.submitted_flag),
            is_correct = submitted_hash == challenge.flag,
            submitted_at=datetime.utcnow()
        )
        db.add(new_sub)
        db.commit()

        return {
            "correct": is_correct,
            "message": "Correct!" if is_correct else "Incorrect flag."
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/leaderboard/")
def get_leaderboard(db: Session = Depends(get_db)):
    result = db.execute(
        select(
            User.username,
            func.sum(Challenge.points).label("score")
        )
        .join(Submission, Submission.user_id == User.id)
        .join(Challenge, Challenge.id == Submission.challenge_id)
        .where(Submission.is_correct == 'true')
        .group_by(User.id, User.username)
        .order_by(func.sum(Challenge.points).desc())
    )

    leaderboard = [{"username": row[0], "score": row[1]} for row in result.all()]
    return leaderboard
