from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class ChallengeAttachment(Base):
    __tablename__ = "challenge_attachments"

    id = Column(Integer, primary_key=True)
    challenge_id = Column(Integer, ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(128), nullable=True)
    storage_backend = Column(String(32), nullable=False)
    storage_path = Column(String(512), nullable=False)
    filesize = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    challenge = relationship("Challenge", back_populates="attachments")
