from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.challenge import Challenge
from app.database import get_db
from app.schemas import ChallengeCreate, ChallengePublic
from app.auth_token import require_admin
from app.routes.auth import hash_flag

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

from datetime import datetime

@router.get("/challenges/", response_model=list[ChallengePublic])
async def list_challenges(db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow()
    result = await db.execute(select(Challenge))
    challenges = result.scalars().all()

    # Apply visibility and time filters
    visible_challenges = [
        c for c in challenges
        if not c.is_private
        and (c.visible_from is None or c.visible_from <= now)
        and (c.visible_to is None or c.visible_to >= now)
    ]

    return visible_challenges


@router.get("/challenges/{challenge_id}", response_model=ChallengePublic)
async def get_challenge(challenge_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return challenge