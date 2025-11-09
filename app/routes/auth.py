
import hashlib
import hmac
import os

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.auth_token import create_access_token, get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas import (
    UserLogin,
    UserProfile,
    UserProfileRead,
    UserProfileUpdate,
    UserRegister,
)
from app.security import pwd_context

router = APIRouter()

def hash_flag(flag: str) -> str:
    return hashlib.sha256(flag.encode("utf-8")).hexdigest()

@router.post("/register")
async def register(user: UserRegister, db: AsyncSession = Depends(get_db)):
    conflict_result = await db.execute(
        select(User).where(
            or_(User.username == user.username, User.email == user.email)
        )
    )
    conflict = conflict_result.scalars().first()
    if conflict:
        if conflict.email == user.email:
            raise HTTPException(status_code=400, detail="Email already exists")
        raise HTTPException(status_code=400, detail="Username already exists")

    if len(user.password) < 8:
        raise HTTPException(status_code=400, detail="Password too short")

    hashed = pwd_context.hash(user.password)
    new_user = User(
        username=user.username,
        email=user.email,
        password_hash=hashed
    )
    db.add(new_user)
    await db.commit()
    return {"message": "Registered successfully"}

@router.post("/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == form_data.username))
    db_user = result.scalar_one_or_none()

    if not db_user or not pwd_context.verify(form_data.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"user_id": db_user.id})
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me", response_model=UserProfileRead)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return UserProfileRead.model_validate(current_user)


@router.patch("/me", response_model=UserProfileRead)
async def update_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    changed = False

    if payload.username and payload.username != current_user.username:
        result = await db.execute(select(User).where(User.username == payload.username))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already taken")
        current_user.username = payload.username
        changed = True

    if payload.email and payload.email != current_user.email:
        result = await db.execute(select(User).where(User.email == payload.email))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")
        current_user.email = payload.email
        changed = True

    if payload.password:
        if len(payload.password) < 8:
            raise HTTPException(status_code=400, detail="Password too short")
        current_user.password_hash = pwd_context.hash(payload.password)
        changed = True

    if payload.display_name is not None:
        current_user.display_name = payload.display_name
        changed = True

    if payload.bio is not None:
        current_user.bio = payload.bio
        changed = True

    if changed:
        db.add(current_user)
        await db.commit()
        await db.refresh(current_user)

    return UserProfileRead.model_validate(current_user)

@router.post("/make-me-admin")
async def make_me_admin(
    payload: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Bootstrap route for promoting a user to admin.

    The route is disabled by default. To enable it for an initial
    bootstrap, set the environment variable ``ENABLE_ADMIN_BOOTSTRAP`` to a
    truthy value and provide a matching ``ADMIN_BOOTSTRAP_TOKEN``. Requests
    must include the token in the JSON body as ``{"token": "..."}``.
    """

    if not os.getenv("ENABLE_ADMIN_BOOTSTRAP", "").lower() in {"1", "true", "yes"}:
        raise HTTPException(status_code=404, detail="Not Found")

    bootstrap_token = os.getenv("ADMIN_BOOTSTRAP_TOKEN")
    if not bootstrap_token:
        raise HTTPException(status_code=403, detail="Admin bootstrap disabled")

    provided_token = payload.get("token")
    if not provided_token or not hmac.compare_digest(provided_token, bootstrap_token):
        raise HTTPException(status_code=403, detail="Invalid bootstrap token")

    if user.role == "admin":
        return {"message": "User is already an admin"}

    user.role = "admin"
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"message": "You are now an admin"}

