# app/auth_token.py
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
import os
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models.user import User

# Load .env if present
load_dotenv()

# ---- ENV VAR COMPAT (supports old & new names) ----
SECRET_KEY = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = os.getenv("JWT_ALGORITHM") or os.getenv("ALGORITHM", "HS256")
try:
    EXPIRY_MINUTES = int(
        os.getenv("JWT_EXPIRY_MINUTES")
        or os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")
        or "60"
    )
except ValueError:
    EXPIRY_MINUTES = 60

# OAuth2 password flow; Swagger's Authorize uses /auth/login to fetch tokens
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    """
    Create a signed JWT with an expiry (UTC).
    `data` should include a `user_id` key.
    """
    to_encode = data.copy()
    minutes = EXPIRY_MINUTES if expires_minutes is None else expires_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Decode JWT, load the current user, or raise 401.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """
    Guard that requires the current user to have role='admin'.
    """
    if getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admins only.")
    return user
