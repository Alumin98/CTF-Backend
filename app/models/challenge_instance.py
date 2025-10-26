from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class ChallengeInstance(Base):
    __tablename__ = "challenge_instances"

    id = Column(Integer, primary_key=True)
    challenge_id = Column(Integer, ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    container_id = Column(String(128), nullable=True)
    connection_info = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    challenge = relationship("Challenge", back_populates="instances")
    user = relationship("User", back_populates="challenge_instances")

    def mark_running(
        self,
        *,
        container_id: str,
        connection_info: Optional[dict],
        started_at: datetime,
        expires_at: Optional[datetime],
    ) -> None:
        self.status = "running"
        self.container_id = container_id
        self.connection_info = connection_info
        self.started_at = started_at
        self.expires_at = expires_at
        self.error_message = None

    def mark_error(self, message: str) -> None:
        self.status = "error"
        self.error_message = message

    def mark_stopped(self) -> None:
        self.status = "stopped"
        self.expires_at = None
