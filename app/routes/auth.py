from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
import hashlib

from app.models.user import User
from app.schemas import UserRegister
from app.database import get_db
from app.auth_token import get_current_user, create_access_token

router = APIRouter()

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_flag(flag: str) -> str:
    return hashlib.sha256(flag.encode("utf-8")).hexdigest()


@router.post("/register")
async def register(user: UserRegister, db: AsyncSession = Depends(get_db)):
    normalized_email = (user.email or "").strip().lower()
    exists = await db.execute(select(User).where(func.lower(User.email) == normalized_email))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already exists")

    if len(user.password or "") < 8:
        raise HTTPException(status_code=400, detail="Password too short")

    hashed = pwd_context.hash(user.password)
    new_user = User(
        username=user.username,
        email=normalized_email,
        password_hash=hashed,
    )
    db.add(new_user)
    await db.commit()
    return {"message": "Registered successfully"}


@router.post("/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    email_in = (form_data.username or "").strip().lower()
    result = await db.execute(select(User).where(func.lower(User.email) == email_in))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_not_found")

    try:
        ok = pwd_context.verify(form_data.password, db_user.password_hash)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"verify_error: {type(e).__name__}: {e}")
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="password_mismatch")

    if getattr(db_user, "mfa_enabled", False):
        return {"mfa_required": True, "message": "MFA enabled for this account. Complete MFA to receive a token."}

    try:
        token = create_access_token({"user_id": db_user.id})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"token_error: {type(e).__name__}: {e}")
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "created_at": current_user.created_at,
        "mfa_enabled": getattr(current_user, "mfa_enabled", False),
    }


@router.post("/make-me-admin")
async def make_me_admin(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.role = "admin"
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"message": "You are now an admin"}


# ---------- DEV-ONLY: list users to confirm emails ----------
@router.get("/dev/users")
async def dev_list_users(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(User.username, User.email))).all()
    return [{"username": r[0], "email": r[1]} for r in rows]


# ---------- MFA toggle endpoints (prep only) ----------
@router.post("/mfa/enable")
async def enable_mfa(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = (await db.execute(select(User).where(User.id == current_user.id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.mfa_enabled = True
    await db.commit()
    return {"ok": True, "mfa_enabled": True}


@router.post("/mfa/disable")
async def disable_mfa(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = (await db.execute(select(User).where(User.id == current_user.id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.mfa_enabled = False
    user.mfa_secret = None
    user.mfa_backup_codes = None
    await db.commit()
    return {"ok": True, "mfa_enabled": False}
