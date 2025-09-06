from datetime import datetime, timedelta, timezone
import os, logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.utils.emailer import send_email
from app.utils.security_tokens import generate_reset_token, hash_token, constant_time_equals
from app.utils.email_templates import reset_link, reset_email_html

link = reset_link(token)
html = reset_email_html(link)

try:

    from app.routes.auth import hashed_password
except Exception:

    import hashlib, os, base64
    def hash_password(plain: str) -> str:  
        salt = os.urandom(16)
        dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, 200_000)
        return base64.b64encode(salt + dk).decode()
    
router = APIRouter(prefix="/auth", tags=["auth"])