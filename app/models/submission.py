from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    challenge_id = Column(Integer, ForeignKey("challenges.id"), nullable=False)
    submitted_hash = Column(String(255), nullable=False)
    is_correct = Column(String(10), nullable=False)  # 'true'/'false' TEXT
    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    first_blood = Column(Boolean, default=False)

    # NEW FIELDS
    points_awarded = Column(Integer, nullable=True)  # actual score given
    used_hint_ids = Column(Text, nullable=True)     # comma-separated hint IDs (e.g., "1,2")

    # relationships if you want
    user = relationship("User", back_populates="submissions", lazy="selectin")
    challenge = relationship("Challenge", back_populates="submissions", lazy="selectin")
