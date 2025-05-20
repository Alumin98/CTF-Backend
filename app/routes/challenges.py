from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.future import select
from app.models.challenge import Challenge
from app.database import get_db
from app.schemas import ChallengeCreate, ChallengePublic
from app.auth_token import get_current_user

router = APIRouter()


@router.post("/challenges/", response_model=ChallengePublic)
async def create_challenge(
    challenge: ChallengeCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    # TODO: add admin check here later
    new_challenge = Challenge(**challenge.dict())
    db.add(new_challenge)
    db.commit()
    db.refresh(new_challenge)
    return new_challenge


@router.get("/challenges/", response_model=list[ChallengePublic])
async def list_challenges(db: Session = Depends(get_db)):
    result =  db.execute(select(Challenge))
    challenges = result.scalars().all()
    return challenges


@router.get("/challenges/{challenge_id}", response_model=ChallengePublic)
async def get_challenge(challenge_id: int, db: Session = Depends(get_db)):
    result = db.execute(select(Challenge).where(Challenge.id == challenge_id))
    challenge = result.scalar()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return challenge