from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi.security import OAuth2PasswordRequestForm

from app.models.user import User
from app.schemas import UserRegister, UserLogin, UserProfile
from app.database import get_db
from app.auth_token import get_current_user, create_access_token
from passlib.hash import argon2

router = APIRouter()

# Flag hashing function
import hashlib
def hash_flag(flag: str) -> str:
    return hashlib.sha256(flag.encode('utf-8')).hexdigest()

@router.post("/register")
def register(user: UserRegister, db: Session = Depends(get_db)):
    result = db.execute(select(User).where(User.email == user.email))
    if result.scalar():
        raise HTTPException(status_code=400, detail="Email already exists")

    hashed = argon2.hash(user.password)
    new_user = User(
        username=user.username,
        email=user.email,
        password_hash=hashed
    )
    db.add(new_user)
    db.commit()
    return {"message": "Registered successfully"}

@router.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    result = db.execute(select(User).where(User.email == form_data.username))
    db_user = result.scalar()

    if not db_user or not argon2.verify(form_data.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"user_id": db_user.id})
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me")
def read_users_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "created_at": current_user.created_at
    }
