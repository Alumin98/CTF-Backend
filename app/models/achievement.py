# app/models/achievement.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base

class AchievementType:
    FIRST_BLOOD = "first_blood"       # first correct solver on a challenge
    FAST_SOLVER = "fast_solver"       # solved within X minutes of release
    CATEGORY_KING = "category_king"   # top scorer in a category (freeze-aware)

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Achievement(Base):
    __tablename__ = "achievements"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), nullable=False, index=True)

    # Scope fields (nullable depending on type)
    challenge_id = Column(Integer, ForeignKey("challenges.id", ondelete="CASCADE"), nullable=True, index=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=True, index=True)

    details = Column(String(255), nullable=True)  # optional: store “reason” or timespan
    points_at_award = Column(Integer, nullable=True)  # optional snapshot
    awarded_at = Column(DateTime, default=utcnow, nullable=False)

    user = relationship("User", lazy="selectin")
    # Challenge/Category relationships are optional

    __table_args__ = (
        # Prevent dupes for the same scope
        UniqueConstraint("user_id", "type", "challenge_id", name="uq_ach_user_type_challenge"),
        UniqueConstraint("user_id", "type", "category_id", name="uq_ach_user_type_category"),
    )
