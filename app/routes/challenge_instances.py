from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_token import get_current_user
from app.database import get_db
from app.models.challenge import Challenge
from app.models.challenge_instance import ChallengeInstance
from app.models.user import User
from app.schemas import ChallengeInstanceRead
from app.services import get_container_service

router = APIRouter(prefix="/challenges", tags=["Challenge Instances"])


async def _latest_instance(db: AsyncSession, challenge_id: int, user_id: int) -> ChallengeInstance | None:
    stmt = (
        select(ChallengeInstance)
        .where(
            ChallengeInstance.challenge_id == challenge_id,
            ChallengeInstance.user_id == user_id,
        )
        .order_by(ChallengeInstance.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


def _is_expired(instance: ChallengeInstance) -> bool:
    if not instance.expires_at:
        return False
    expires = instance.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires < datetime.now(timezone.utc)


@router.get("/{challenge_id}/instance", response_model=ChallengeInstanceRead)
async def get_instance(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = await _latest_instance(db, challenge_id, user.id)
    if not instance:
        raise HTTPException(status_code=404, detail="No instance")
    return ChallengeInstanceRead.model_validate(instance)


@router.post("/{challenge_id}/instance", response_model=ChallengeInstanceRead)
async def start_instance(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge = await db.get(Challenge, challenge_id)
    if not challenge or not challenge.is_active:
        raise HTTPException(status_code=404, detail="Challenge not available")
    if not challenge.docker_image:
        raise HTTPException(status_code=400, detail="Challenge does not support dynamic instances")

    now = datetime.now(timezone.utc)
    if challenge.visible_from and now < challenge.visible_from.replace(tzinfo=challenge.visible_from.tzinfo or timezone.utc):
        raise HTTPException(status_code=403, detail="Challenge not yet visible")
    if challenge.visible_to:
        visible_to = challenge.visible_to.replace(tzinfo=challenge.visible_to.tzinfo or timezone.utc)
        if now > visible_to:
            raise HTTPException(status_code=403, detail="Challenge no longer available")

    existing = await _latest_instance(db, challenge_id, user.id)
    if existing and existing.status == "running" and not _is_expired(existing):
        return ChallengeInstanceRead.model_validate(existing)

    instance = ChallengeInstance(
        challenge_id=challenge_id,
        user_id=user.id,
        status="pending",
    )
    db.add(instance)
    await db.flush()
    await db.refresh(instance)

    service = get_container_service()
    instance = await service.provision_instance(session=db, instance=instance, challenge=challenge)
    return ChallengeInstanceRead.model_validate(instance)


@router.delete("/{challenge_id}/instance", response_model=ChallengeInstanceRead)
async def stop_instance(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = await _latest_instance(db, challenge_id, user.id)
    if not instance:
        raise HTTPException(status_code=404, detail="No instance")

    service = get_container_service()
    instance = await service.terminate_instance(session=db, instance=instance)
    return ChallengeInstanceRead.model_validate(instance)
