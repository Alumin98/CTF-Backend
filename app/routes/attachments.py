from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.challenge import Challenge
from app.models.challenge_attachment import ChallengeAttachment
from app.schemas import AttachmentRead
from app.services import get_attachment_storage

router = APIRouter(prefix="/challenges", tags=["Challenge Attachments"])


def _challenge_visible(challenge: Challenge) -> bool:
    if not challenge.is_active or challenge.is_private:
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


@router.get("/{challenge_id}/attachments", response_model=list[AttachmentRead])
async def list_attachments(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
):
    challenge = await db.get(Challenge, challenge_id)
    if not challenge or not _challenge_visible(challenge):
        raise HTTPException(status_code=404, detail="Challenge not available")

    return [
        AttachmentRead(
            id=a.id,
            filename=a.filename,
            content_type=a.content_type,
            filesize=a.filesize,
            url=f"/challenges/{challenge_id}/attachments/{a.id}",
        )
        for a in sorted(challenge.attachments or [], key=lambda att: att.id)
    ]


@router.get("/{challenge_id}/attachments/{attachment_id}")
async def download_attachment(
    challenge_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ChallengeAttachment)
        .join(Challenge, Challenge.id == ChallengeAttachment.challenge_id)
        .where(
            ChallengeAttachment.id == attachment_id,
            ChallengeAttachment.challenge_id == challenge_id,
        )
    )
    result = await db.execute(stmt)
    attachment = result.scalars().first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    challenge = attachment.challenge
    if not _challenge_visible(challenge):
        raise HTTPException(status_code=403, detail="Challenge not accessible")

    storage = get_attachment_storage()
    if attachment.storage_backend == "s3":
        url = await storage.signed_url(attachment)
        if not url:
            raise HTTPException(status_code=500, detail="Failed to generate download URL")
        return JSONResponse({"url": url})

    stream = await storage.open(attachment)
    headers = {
        "Content-Disposition": f'attachment; filename="{attachment.filename}"'
    }
    return StreamingResponse(
        stream,
        media_type=attachment.content_type or "application/octet-stream",
        headers=headers,
    )
