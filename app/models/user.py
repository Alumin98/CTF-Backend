# app/models/user.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func, Boolean
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    # core identity
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True)

    # auth
    password_hash = Column("hashed_password", String, nullable=False)
    role = Column(String, default="player")

    # relationships
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)

    # housekeeping
    created_at = Column(DateTime, default=func.now())

    # --------------------------
    # MFA (prep-only)
    # --------------------------
    # if True, login should *not* issue a JWT yet — it should ask for MFA first
    mfa_enabled = Column(Boolean, nullable=False, default=False)
    # reserved for a future TOTP secret (e.g., base32)
    mfa_secret = Column(String(64), nullable=True)
    # optional: comma-separated hashed backup codes (future use)
    mfa_backup_codes = Column(String, nullable=True)
