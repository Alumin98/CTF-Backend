import logging
from datetime import timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.auth_token import get_current_user
from app.models.user import User
from app.models.challenge import Challenge
from app.models.hint import Hint
from app.models.challenge_tag import ChallengeTag
from app.models.submission import Submission  # used to count solves
from app.routes.auth import hash_flag
from app.schemas import (
    ChallengeCreate, ChallengeUpdate, ChallengeAdmin, HintCreate
)

admin = APIRouter(prefix="/admin/challenges", tags=["Admin: Challenges"])
logger = logging.getLogger(__name__)


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

def _to_admin_schema(ch: Challenge, solves: int) -> ChallengeAdmin:
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
        tags=ch.tag_strings,
        hints=sorted(ch.hints or [], key=lambda h: h.order_index),
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
    await db.refresh(ch)

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
        "title", "description", "category_id", "points", "difficulty",
        "docker_image", "competition_id", "unlocked_by_id",
        "is_active", "is_private", "visible_from", "visible_to",
    ]:
        val = getattr(payload, field)
        if val is not None:
            if field in {"visible_from", "visible_to"}:
                val = _as_naive_utc(val)
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
    await db.refresh(ch)

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
