import os
from datetime import datetime, timezone
from urllib.parse import urljoin

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_token import get_current_user, require_admin
from app.database import get_db
from app.flag_storage import hash_flag
from app.models.challenge import Challenge
from app.models.challenge_attachment import ChallengeAttachment
from app.models.challenge_instance import ChallengeInstance
from app.models.hint import Hint
from app.models.submission import Submission
from app.models.team import Team
from app.models.user import User
from app.schemas import (
    AttachmentRead,
    ChallengeCreate,
    ChallengeInstanceRead,
    ChallengePublic,
    HintRead,
)
from app.services.container_service import get_container_service

router = APIRouter()


def _attachment_url(challenge_id: int, attachment_id: int) -> str:
    base = os.getenv("CHALLENGE_ACCESS_BASE_URL", "").strip()
    path = f"/challenges/{challenge_id}/attachments/{attachment_id}"
    if not base:
        return path
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))

_optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user_optional(
    token: str | None = Depends(_optional_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not token:
        return None
    try:
        return await get_current_user(token=token, db=db)
    except HTTPException:
        return None


def _attachment_to_schema(challenge_id: int, attachment: ChallengeAttachment) -> AttachmentRead:
    return AttachmentRead(
        id=attachment.id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        url=_attachment_url(challenge_id, attachment.id),
        filesize=attachment.filesize,
    )


def _hint_to_schema(hint: Hint) -> HintRead:
    return HintRead(
        id=getattr(hint, "id", 0),
        text=hint.text,
        penalty=hint.penalty,
        order_index=hint.order_index,
    )


def _challenge_to_public(
    challenge: Challenge,
    solves: int = 0,
    instance: ChallengeInstance | None = None,
) -> ChallengePublic:
    hints = sorted(getattr(challenge, "hints", []) or [], key=lambda h: getattr(h, "order_index", 0))
    attachments = getattr(challenge, "attachments", []) or []
    service = get_container_service()
    access_url = service.build_access_url(challenge=challenge, instance=instance)
    active_instance = None
    if instance is not None:
        instance_access_url = access_url or service.build_access_url(
            challenge=challenge, instance=instance
        )
        base = ChallengeInstanceRead.model_validate(instance)
        active_instance = base.model_copy(update={"access_url": instance_access_url})
    return ChallengePublic(
        id=challenge.id,
        title=challenge.title,
        description=challenge.description,
        category_id=getattr(challenge, "category_id", None),
        points=challenge.points,
        difficulty=challenge.difficulty,
        created_at=getattr(challenge, "created_at", None),
        competition_id=getattr(challenge, "competition_id", None),
        unlocked_by_id=getattr(challenge, "unlocked_by_id", None),
        is_active=challenge.is_active,
        is_private=challenge.is_private,
        visible_from=getattr(challenge, "visible_from", None),
        visible_to=getattr(challenge, "visible_to", None),
        deployment_type=getattr(challenge, "deployment_type", "static_attachment"),
        service_port=getattr(challenge, "service_port", None),
        always_on=bool(getattr(challenge, "always_on", False)),
        tags=challenge.tag_strings,
        hints=[_hint_to_schema(h) for h in hints],
        attachments=[_attachment_to_schema(challenge.id, att) for att in attachments],
        active_instance=active_instance,
        access_url=access_url,
        solves_count=solves,
    )


def _as_aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _select_display_instance(instance: ChallengeInstance) -> ChallengeInstance | None:
    if instance.status not in ChallengeInstance.ACTIVE_STATUSES:
        return None

    def _as_aware(dt):
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    instance.started_at = _as_aware(getattr(instance, "started_at", None))
    instance.expires_at = _as_aware(getattr(instance, "expires_at", None))

    if instance.is_expired():
        return None
    return instance


@router.post("/challenges/", response_model=ChallengePublic)
async def create_challenge(
    challenge: ChallengeCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    try:
        data = challenge.dict()

        # Map fields + hash flag
        data["flag"] = hash_flag(challenge.flag) if challenge.flag is not None else None
        data["visible_from"] = data.pop("start_time", None)
        data["visible_to"] = data.pop("end_time", None)

        # Pull relationship inputs out BEFORE constructing the model
        tags = data.pop("tags", None)
        hints = data.pop("hints", None)

        new_ch = Challenge(**data)

        # Apply hints
        if hints:
            for h in hints:
                new_ch.hints.append(
                    Hint(text=h["text"], penalty=h["penalty"], order_index=h["order_index"])
                    if isinstance(h, dict)
                    else Hint(text=h.text, penalty=h.penalty, order_index=h.order_index)
                )

        # Apply tags (if your model has this helper)
        if tags:
            new_ch.set_tag_strings(tags)

        db.add(new_ch)
        await db.commit()
        await db.refresh(new_ch)

        return ChallengePublic(
            id=new_ch.id,
            title=new_ch.title,
            description=new_ch.description,
            category_id=getattr(new_ch, "category_id", None),
            points=new_ch.points,
            difficulty=new_ch.difficulty,
            is_active=new_ch.is_active,
            start_time=new_ch.visible_from,
            end_time=new_ch.visible_to,
            created_at=getattr(new_ch, "created_at", None),
            solves=0,
        )
        await db.refresh(new_ch, attribute_names=["hints", "tags", "attachments"])

        return _challenge_to_public(new_ch)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/challenges/", response_model=list[ChallengePublic])
async def list_challenges(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Return active challenges whose time window includes 'now'.
    Model uses visible_from/visible_to; API uses start_time/end_time.
    """
    res = await db.execute(select(Challenge))
    rows = res.scalars().all()

    now = datetime.now(timezone.utc)

    instances_by_challenge: dict[int, ChallengeInstance] = {}
    if current_user:
        challenge_ids = [c.id for c in rows if getattr(c, "id", None) is not None]
        if challenge_ids:
            stmt_instances = (
                select(ChallengeInstance)
                .where(
                    ChallengeInstance.user_id == current_user.id,
                    ChallengeInstance.challenge_id.in_(challenge_ids),
                )
                .order_by(ChallengeInstance.challenge_id, ChallengeInstance.created_at.desc())
            )
            instance_rows = await db.execute(stmt_instances)
            for inst in instance_rows.scalars().all():
                if inst.challenge_id in instances_by_challenge:
                    continue
                display_instance = _select_display_instance(inst)
                if display_instance:
                    instances_by_challenge[inst.challenge_id] = display_instance

    visible: list[ChallengePublic] = []
    for c in rows:
        if not c.is_active:
            continue

        st = _as_aware(getattr(c, "visible_from", None))
        et = _as_aware(getattr(c, "visible_to", None))

        if st and now < st:
            continue
        if et and now > et:
            continue

        visible.append(
            _challenge_to_public(
                c,
                instance=instances_by_challenge.get(getattr(c, "id", None)),
            )
        )
    return visible


@router.patch("/challenges/{challenge_id}", response_model=ChallengePublic)
async def update_challenge(
    challenge_id: int,
    challenge_update: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Challenge not found")

    # Map API -> model where needed
    if "flag" in challenge_update:
        challenge_update["flag"] = hash_flag(challenge_update["flag"])
    if "start_time" in challenge_update:
        challenge_update["visible_from"] = challenge_update.pop("start_time")
    if "end_time" in challenge_update:
        challenge_update["visible_to"] = challenge_update.pop("end_time")

    for k, v in challenge_update.items():
        setattr(ch, k, v)

    await db.commit()
    await db.refresh(ch, attribute_names=["hints", "tags", "attachments"])

    return _challenge_to_public(ch)


@router.delete("/challenges/{challenge_id}", status_code=204)
async def delete_challenge(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Challenge not found")
    await db.delete(ch)
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
        .where(Submission.challenge_id == challenge_id, Submission.is_correct == True)
        .order_by(Submission.submitted_at)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "team": team.team_name if team else None,
            "user": user.username,
            "timestamp": submission.submitted_at.isoformat(),
            "first_blood": getattr(submission, "first_blood", False),
        }
        for submission, user, team in rows
    ]
