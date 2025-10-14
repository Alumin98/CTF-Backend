# app/models/submission.py
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, ForeignKey, DateTime, Boolean, Text,
    Index
)
from sqlalchemy.orm import relationship
from app.database import Base


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)

    # If a user or challenge is deleted, we usually want submissions gone too
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    challenge_id = Column(Integer, ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False, index=True)

    # Legacy databases store this value in the ``submitted_flag`` column.
    submitted_hash = Column("submitted_flag", String(255), nullable=False)
    # Stored as TEXT 'true' / 'false' (your routes cast to Boolean when filtering)
    is_correct = Column(String(10), nullable=False, default="false")

    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    first_blood = Column(Boolean, nullable=False, default=False)

    # Persisted scoring + hint usage (added in your DB already)
    points_awarded = Column(Integer, nullable=True)   # score granted for this submission (0 or None if incorrect)
    used_hint_ids = Column(Text, nullable=True)       # comma-separated hint IDs, e.g. "1,2,5"

    # ORM relationships (ensure matching back_populates exist; see notes below)
    user = relationship("User", back_populates="submissions", lazy="selectin")
    challenge = relationship("Challenge", back_populates="submissions", lazy="selectin")

    # Handy composite indexes for common queries (leaderboard, solvers, dedup checks)
    __table_args__ = (
        # Count solves for a challenge quickly and order by time
        Index("ix_submissions_challenge_time", "challenge_id", "submitted_at"),
        # Filter “correct” rows fast (remember: is_correct is TEXT)
        Index("ix_submissions_challenge_correct", "challenge_id", "is_correct"),
        # Check “has this user already solved this challenge?” fast
        Index("ix_submissions_user_challenge_correct", "user_id", "challenge_id", "is_correct"),
    )

    def __repr__(self) -> str:
        return f"<Submission id={self.id} user={self.user_id} chal={self.challenge_id} correct={self.is_correct}>"
