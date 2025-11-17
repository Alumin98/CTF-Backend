import os
from datetime import datetime, timezone
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_token import get_current_user, require_admin
from app.database import get_db
from app.flag_storage import hash_flag
from app.models.challenge import Challenge, DeploymentType
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
    ChallengeUpdate,
    HintCreate,
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
    deployment_type = getattr(challenge, "deployment_type", DeploymentType.dynamic_container)
    if isinstance(deployment_type, str):
        try:
            deployment_type = DeploymentType(deployment_type)
        except ValueError:
            deployment_type = DeploymentType.dynamic_container
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
        deployment_type=deployment_type,
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


def _as_naive(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is None else dt.astimezone(timezone.utc).replace(tzinfo=None)


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
        data = challenge.model_dump()
        tags = data.pop("tags", [])
        hints_payload = data.pop("hints", [])
        flag_value = data.pop("flag")
        data["flag"] = hash_flag(flag_value)
        if data.get("visible_from") is not None:
            data["visible_from"] = _as_naive(data["visible_from"])
        if data.get("visible_to") is not None:
            data["visible_to"] = _as_naive(data["visible_to"])

        new_ch = Challenge(**data)

        for hint in hints_payload:
            if isinstance(hint, HintCreate):
                hint_obj = hint
            else:
                hint_obj = HintCreate(**hint)
            new_ch.hints.append(
                Hint(text=hint_obj.text, penalty=hint_obj.penalty, order_index=hint_obj.order_index)
            )

        if tags:
            new_ch.set_tag_strings(tags)

        db.add(new_ch)
        await db.commit()
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

    service = get_container_service()
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

    shared_instances: dict[int, ChallengeInstance] = {}
    for c in rows:
        deployment = getattr(c, "deployment_type", DeploymentType.dynamic_container)
        if isinstance(deployment, str):
            try:
                deployment = DeploymentType(deployment)
            except ValueError:
                deployment = DeploymentType.dynamic_container
        if deployment == DeploymentType.static_container:
            shared = await service.get_shared_instance(db, challenge_id=c.id)
            if shared:
                shared_instances[c.id] = shared

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

        instance = instances_by_challenge.get(getattr(c, "id", None))
        if instance is None:
            instance = shared_instances.get(getattr(c, "id", None))
        visible.append(_challenge_to_public(c, instance=instance))
    return visible


@router.patch("/challenges/{challenge_id}", response_model=ChallengePublic)
async def update_challenge(
    challenge_id: int,
    challenge_update: ChallengeUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Challenge not found")

    update_payload = challenge_update.model_dump(exclude_unset=True)
    tags = update_payload.pop("tags", None)
    hints_payload = update_payload.pop("hints", None)

    # Map API -> model where needed
    if "flag" in update_payload:
        update_payload["flag"] = hash_flag(update_payload["flag"])
    if "start_time" in update_payload:
        update_payload["visible_from"] = update_payload.pop("start_time")
    if "end_time" in update_payload:
        update_payload["visible_to"] = update_payload.pop("end_time")
    if "deployment_type" in update_payload and update_payload["deployment_type"] is not None:
        update_payload["deployment_type"] = DeploymentType(update_payload["deployment_type"])

    for k, v in update_payload.items():
        if k in {"visible_from", "visible_to"} and v is not None:
            v = _as_naive(v)
        setattr(ch, k, v)

    if tags is not None:
        ch.set_tag_strings(tags)

    if hints_payload is not None:
        ch.hints.clear()
        for hint in hints_payload:
            if isinstance(hint, HintCreate):
                hint_obj = hint
            else:
                hint_obj = HintCreate(**hint)
            ch.hints.append(
                Hint(text=hint_obj.text, penalty=hint_obj.penalty, order_index=hint_obj.order_index)
            )

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
