# app/routes/password_reset.py
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.emailer import send_email
from app.security_tokens import generate_reset_token, hash_token, constant_time_equals
from app.email_templates import reset_link, reset_email_html
from app.routes.auth import hashed_password

router = APIRouter(prefix="/auth", tags=["auth"])

class ForgotPasswordIn(BaseModel):
    email: EmailStr
    @field_validator("email")
    @classmethod
    def normalize(cls, v: str) -> str:
        return v.strip().lower()

class ResetPasswordIn(BaseModel):
    token: str
    new_password: str

@router.post("/password/forgot")
async def forgot_password(
    body: ForgotPasswordIn,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Look up user (anti-enumeration: same response either way)
    res = await db.execute(select(User).where(User.email == body.email))
    user = res.scalar_one_or_none()

    if user:
        token = generate_reset_token()
        user.reset_token_hash = hash_token(token)
        user.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=60)
        await db.commit()

        link = reset_link(token)                # <-- build here
        html = reset_email_html(link)           # <-- build here
        text = f"Use this link to reset your password (valid 60 minutes): {link}"
        background.add_task(send_email, user.email, "Reset your CTF account password", html, text)

    return {"ok": True, "message": "If that email exists, you’ll receive reset instructions."}

@router.post("/password/reset")
async def reset_password(
    body: ResetPasswordIn,
    db: AsyncSession = Depends(get_db),
):
    token_hash = hash_token(body.token)
    now = datetime.now(timezone.utc)

    res = await db.execute(select(User).where(User.reset_token_hash == token_hash))
    user = res.scalar_one_or_none()

    if not user or not user.reset_token_expires_at or user.reset_token_expires_at < now:
        raise HTTPException(status_code=400, detail="Invalid or expired token.")
    if not constant_time_equals(user.reset_token_hash, token_hash):
        raise HTTPException(status_code=400, detail="Invalid or expired token.")

    user.hashed_password = hashed_password(body.new_password)  # <-- Argon2
    user.reset_token_hash = None
    user.reset_token_expires_at = None
    await db.commit()

    return {"ok": True}
