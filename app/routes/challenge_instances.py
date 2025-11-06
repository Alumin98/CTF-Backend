from __future__ import annotations
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_token import get_current_user
from app.database import get_db
from app.models.challenge import Challenge
from app.models.challenge_instance import ChallengeInstance
from app.models.user import User
from app.schemas import ChallengeInstanceRead
from app.services.container_service import (
    InstanceLaunchError,
    InstanceNotAllowed,
    get_container_service,
)

router = APIRouter(prefix="/challenges/{challenge_id}/instances", tags=["Challenge Instances"])


def _challenge_visible(challenge: Challenge) -> bool:
    if not challenge.is_active or getattr(challenge, "is_private", False):
        return False
    now = datetime.now(timezone.utc)
    if challenge.visible_from:
        start = challenge.visible_from
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if now < start:
            return False
    if challenge.visible_to:
        end = challenge.visible_to
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if now > end:
            return False
    return True


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


@router.post("/start", response_model=ChallengeInstanceRead)
async def start_instance(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge = await db.get(Challenge, challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if not _challenge_visible(challenge):
        raise HTTPException(status_code=403, detail="Challenge not available")

    service = get_container_service()
    try:
        instance = await service.start_instance(db, challenge=challenge, user=user)
    except InstanceNotAllowed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InstanceLaunchError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start challenge instance: {exc}") from exc

    access_url = service.build_access_url(challenge=challenge, instance=instance)
    base = ChallengeInstanceRead.model_validate(instance)
    return base.model_copy(update={"access_url": access_url})


@router.get("/me", response_model=ChallengeInstanceRead)
async def get_my_instance(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge = await db.get(Challenge, challenge_id)
    if not challenge or not _challenge_visible(challenge):
        raise HTTPException(status_code=404, detail="Challenge not available")

    service = get_container_service()
    instance = await service.get_latest_active_instance(db, challenge_id=challenge_id, user_id=user.id)
    if not instance:
        raise HTTPException(status_code=404, detail="No active instance")

    access_url = service.build_access_url(challenge=challenge, instance=instance)
    base = ChallengeInstanceRead.model_validate(instance)
    return base.model_copy(update={"access_url": access_url})


@router.delete("/stop", status_code=status.HTTP_204_NO_CONTENT)
async def stop_instance(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = get_container_service()
    instance = await service.get_latest_active_instance(db, challenge_id=challenge_id, user_id=user.id)
    if not instance:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    await service.stop_instance(db, instance=instance)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
