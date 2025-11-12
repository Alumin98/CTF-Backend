import logging
import os
from datetime import timezone
from typing import List, Optional
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.auth_token import get_current_user
from app.models.user import User
from app.models.challenge import Challenge, DeploymentType
from app.models.hint import Hint
from app.models.challenge_tag import ChallengeTag
from app.models.submission import Submission  # used to count solves
from app.models.challenge_attachment import ChallengeAttachment
from app.flag_storage import hash_flag
from app.schemas import (
    ChallengeCreate, ChallengeUpdate, ChallengeAdmin, HintCreate, AttachmentRead
)
from app.services import get_attachment_storage

admin = APIRouter(prefix="/admin/challenges", tags=["Admin: Challenges"])
logger = logging.getLogger(__name__)


def _attachment_url(challenge_id: int, attachment_id: int) -> str:
    base = os.getenv("CHALLENGE_ACCESS_BASE_URL", "").strip()
    path = f"/challenges/{challenge_id}/attachments/{attachment_id}"
    if not base:
        return path
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))


def _looks_like_hashed_flag(value: Optional[str]) -> bool:
    if not value:
        return False
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except (TypeError, ValueError):
        return False
    return True


def _warn_if_plaintext_flag(ch: Challenge) -> None:
    if ch.flag and not _looks_like_hashed_flag(ch.flag):
        logger.warning(
            "Challenge %s appears to store a plain-text flag. "
            "Consider migrating existing records to hashed values.",
            ch.id,
        )


def _as_naive_utc(dt):
    """Return a timezone-naive datetime in UTC for storage."""

    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)

def _is_admin(user: User) -> bool:
    """Return True when the current user should be treated as an admin."""

    role = getattr(user, "role", None)
    if isinstance(role, str) and role.lower() == "admin":
        return True

    # Legacy flags (older deployments may still rely on these attributes).
    for legacy_flag in ("is_admin", "is_superuser"):
        if getattr(user, legacy_flag, False):
            return True

    return False

async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not _is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user

async def _solves_count(db: AsyncSession, challenge_id: int) -> int:
    q = select(func.count(Submission.id)).where(
        Submission.challenge_id == challenge_id,
        Submission.is_correct == True,   # noqa: E712
    )
    return (await db.execute(q)).scalar_one()

def _deployment_value(ch: Challenge) -> DeploymentType:
    deployment = getattr(ch, "deployment_type", DeploymentType.dynamic_container)
    if isinstance(deployment, str):
        try:
            deployment = DeploymentType(deployment)
        except ValueError:
            deployment = DeploymentType.dynamic_container
    return deployment


def _to_admin_schema(ch: Challenge, solves: int) -> ChallengeAdmin:
    attachments = [
        AttachmentRead(
            id=a.id,
            filename=a.filename,
            content_type=a.content_type,
            filesize=a.filesize,
            url=_attachment_url(ch.id, a.id),
        )
        for a in sorted(getattr(ch, "attachments", []) or [], key=lambda att: att.id)
    ]
    return ChallengeAdmin(
        id=ch.id,
        title=ch.title,
        description=ch.description or "",
        category_id=ch.category_id,
        points=ch.points or 0,
        difficulty=ch.difficulty,
        created_at=ch.created_at,
        competition_id=ch.competition_id,
        unlocked_by_id=ch.unlocked_by_id,
        is_active=bool(ch.is_active),
        is_private=bool(ch.is_private),
        visible_from=ch.visible_from,
        visible_to=ch.visible_to,
        deployment_type=_deployment_value(ch),
        service_port=getattr(ch, "service_port", None),
        always_on=bool(getattr(ch, "always_on", False)),
        tags=ch.tag_strings,
        hints=sorted(ch.hints or [], key=lambda h: h.order_index),
        attachments=attachments,
        solves_count=solves,
    )

@admin.post("", response_model=ChallengeAdmin, status_code=201)
async def create_challenge(
    payload: ChallengeCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    ch = Challenge(
        title=payload.title,
        description=payload.description,
        category_id=payload.category_id,
        points=payload.points,
        difficulty=payload.difficulty or "easy",
        docker_image=payload.docker_image,
        deployment_type=payload.deployment_type,
        service_port=payload.service_port,
        always_on=bool(payload.always_on),
        is_active=True if payload.is_active is None else payload.is_active,
        is_private=False if payload.is_private is None else payload.is_private,
        visible_from=_as_naive_utc(payload.visible_from),
        visible_to=_as_naive_utc(payload.visible_to),
        competition_id=payload.competition_id,
        unlocked_by_id=payload.unlocked_by_id,
        flag=hash_flag(payload.flag) if payload.flag is not None else None,
    )
    # hints
    for h in payload.hints or []:
        ch.hints.append(Hint(text=h.text, penalty=h.penalty, order_index=h.order_index))

    # tags
    ch.set_tag_strings(payload.tags or [])

    db.add(ch)
    await db.flush()  # get ch.id

    await db.commit()
    await db.refresh(ch, attribute_names=["attachments", "hints", "tags"])

    solves = await _solves_count(db, ch.id)
    return _to_admin_schema(ch, solves)

@admin.get("", response_model=List[ChallengeAdmin])
async def list_challenges_admin(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
    category_id: Optional[int] = Query(None),
    difficulty: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
):
    stmt = select(Challenge).order_by(Challenge.created_at.desc())
    if category_id is not None:
        stmt = stmt.where(Challenge.category_id == category_id)
    if difficulty:
        stmt = stmt.where(Challenge.difficulty == difficulty)
    if tag:
        stmt = stmt.join(ChallengeTag).where(ChallengeTag.tag == tag)

    rows = (await db.execute(stmt)).scalars().unique().all()

    # one query per solves count keeps it simple; can batch later if needed
    out: List[ChallengeAdmin] = []
    for ch in rows:
        solves = await _solves_count(db, ch.id)
        out.append(_to_admin_schema(ch, solves))
    return out

@admin.get("/{challenge_id}", response_model=ChallengeAdmin)
async def get_challenge_admin(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    ch = await db.get(Challenge, challenge_id)
    if not ch:
        raise HTTPException(404, "Challenge not found")
    solves = await _solves_count(db, ch.id)
    return _to_admin_schema(ch, solves)


@admin.post("/{challenge_id}/attachments", response_model=AttachmentRead, status_code=201)
async def upload_attachment_admin(
    challenge_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    challenge = await db.get(Challenge, challenge_id)
    if not challenge:
        raise HTTPException(404, "Challenge not found")

    storage = get_attachment_storage()
    original_name = file.filename or "attachment.bin"
    result = await storage.save(challenge_id, file)
    attachment = ChallengeAttachment(
        challenge_id=challenge_id,
        filename=original_name,
        content_type=file.content_type,
        storage_backend=result.backend,
        storage_path=result.path,
        filesize=result.size,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return AttachmentRead(
        id=attachment.id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        filesize=attachment.filesize,
        url=_attachment_url(challenge_id, attachment.id),
    )


@admin.delete("/{challenge_id}/attachments/{attachment_id}", status_code=204)
async def delete_attachment_admin(
    challenge_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    attachment = await db.get(ChallengeAttachment, attachment_id)
    if not attachment or attachment.challenge_id != challenge_id:
        raise HTTPException(404, "Attachment not found")
    storage = get_attachment_storage()
    await storage.delete(attachment)
    await db.delete(attachment)
    await db.commit()

@admin.patch("/{challenge_id}", response_model=ChallengeAdmin)
async def update_challenge_admin(
    challenge_id: int,
    payload: ChallengeUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    ch = await db.get(Challenge, challenge_id)
    if not ch:
        raise HTTPException(404, "Challenge not found")

    # scalar fields
    for field in [
        "title",
        "description",
        "category_id",
        "points",
        "difficulty",
        "docker_image",
        "competition_id",
        "unlocked_by_id",
        "deployment_type",
        "service_port",
        "always_on",
        "is_active",
        "is_private",
        "visible_from",
        "visible_to",
    ]:
        val = getattr(payload, field)
        if val is not None:
            if field in {"visible_from", "visible_to"}:
                val = _as_naive_utc(val)
            if field == "deployment_type":
                val = DeploymentType(val)
            setattr(ch, field, val)

    # flag update (write-only)
    if payload.flag is not None:
        ch.flag = hash_flag(payload.flag)
    else:
        _warn_if_plaintext_flag(ch)

    # tags (full replace if provided)
    if payload.tags is not None:
        await db.refresh(ch, attribute_names=["tags"])
        ch.set_tag_strings(payload.tags)

    # hints (full replace if provided)
    if payload.hints is not None:
        ch.hints.clear()
        for h in payload.hints:
            ch.hints.append(Hint(text=h.text, penalty=h.penalty, order_index=h.order_index))

    await db.commit()
    await db.refresh(ch, attribute_names=["attachments", "hints", "tags"])

    solves = await _solves_count(db, ch.id)
    return _to_admin_schema(ch, solves)

@admin.delete("/{challenge_id}", status_code=204)
async def delete_challenge_admin(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    ch = await db.get(Challenge, challenge_id)
    if not ch:
        return
    await db.delete(ch)
    await db.commit()
