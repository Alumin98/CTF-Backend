from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.challenge import Challenge
from app.database import get_db
from fastapi import Body
from app.schemas import ChallengeCreate, ChallengePublic
from app.auth_token import require_admin
from app.routes.auth import hash_flag
from app.models.submission import Submission
from app.models.user import User
from app.models.team import Team

router = APIRouter()

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
    current_user: User = Depends(),  # this should be a user-dependency if you have auth
):
    result = await db.execute(select(Challenge))
    challenges = result.scalars().all()

    # Filter based on unlock logic
    unlocked_challenges = []

    for challenge in challenges:
        if challenge.unlocked_by_id is None:
            unlocked_challenges.append(challenge)
        else:
            # check if current_user has solved the unlocked_by_id challenge
            subquery = await db.execute(
                select(Submission)
                .where(
                    Submission.user_id == current_user.id,
                    Submission.challenge_id == challenge.unlocked_by_id,
                    Submission.is_correct == True
                )
            )
            if subquery.first():
                unlocked_challenges.append(challenge)

    return unlocked_challenges

@router.get("/challenges/{challenge_id}", response_model=ChallengePublic)
async def get_challenge(challenge_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return challenge

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
        .join(Team, User.team_id == Team.id, isouter=True) # safer for users without team
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
            "team": team.team_name,
            "user": user.username,
            "timestamp": submission.submitted_at.isoformat()
	    "first_blood": submission.first_blood
        }
        for submission, user, team in rows
    ]
    return solvers