from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.challenge import Challenge
from app.database import get_db
from app.schemas import ChallengeCreate, ChallengePublic
from app.auth_token import require_admin
from app.routes.auth import hash_flag
from app.models.submission import Submission
from app.models.user import User
from app.models.team import Team

router = APIRouter()

# Dependency for getting current user (replace with your actual dependency)
def get_current_user():
    # Implement your user retrieval logic here
    pass

@router.post("/challenges/", response_model=ChallengePublic)
async def create_challenge(
    challenge: ChallengeCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    challenge_data = challenge.dict()
    challenge_data['flag'] = hash_flag(challenge.flag)
    new_challenge = Challenge(**challenge_data)
    db.add(new_challenge)
    await db.commit()
    await db.refresh(new_challenge)
    return new_challenge

@router.get("/challenges/", response_model=list[ChallengePublic])
async def list_challenges(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Use actual dependency
):
    from datetime import datetime

    now = datetime.utcnow()

    result = await db.execute(select(Challenge))
    challenges = result.scalars().all()

    unlocked_challenges = []
    for challenge in challenges:
        is_unlocked = False
        if challenge.unlocked_by_id is None:
            is_unlocked = True
        else:
            subquery = await db.execute(
                select(Submission)
                .where(
                    Submission.user_id == current_user.id,
                    Submission.challenge_id == challenge.unlocked_by_id,
                    Submission.is_correct == True
                )
            )
            if subquery.first():
                is_unlocked = True

        if is_unlocked:
            if not challenge.is_private \
                and (challenge.visible_from is None or challenge.visible_from <= now) \
                and (challenge.visible_to is None or challenge.visible_to >= now):
                unlocked_challenges.append(challenge)

    return unlocked_challenges

@router.patch("/challenges/{challenge_id}", response_model=ChallengePublic)
async def update_challenge(
    challenge_id: int,
    challenge_update: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    if "flag" in challenge_update:
        challenge_update["flag"] = hash_flag(challenge_update["flag"])

    for key, value in challenge_update.items():
        setattr(challenge, key, value)

    await db.commit()
    await db.refresh(challenge)
    return challenge

@router.delete("/challenges/{challenge_id}", status_code=204)
async def delete_challenge(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    await db.delete(challenge)
    await db.commit()
    return None

@router.get("/challenges/{challenge_id}/solvers")
async def get_challenge_solvers(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Submission, User, Team)
        .join(User, Submission.user_id == User.id)
        .join(Team, User.team_id == Team.id, isouter=True)
        .where(
            Submission.challenge_id == challenge_id,
            Submission.is_correct == True
        )
        .order_by(Submission.submitted_at)
    )
    result = await db.execute(stmt)
    rows = result.all()

    solvers = [
        {
            "team": team.team_name if team else None,
            "user": user.username,
            "timestamp": submission.submitted_at.isoformat(),
            "first_blood": getattr(submission, "first_blood", False)
        }
        for submission, user, team in rows
    ]
    return solvers
