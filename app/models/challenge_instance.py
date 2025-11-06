from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class ChallengeInstance(Base):
    __tablename__ = "challenge_instances"

    ACTIVE_STATUSES = {"starting", "running"}

    id = Column(Integer, primary_key=True)
    challenge_id = Column(Integer, ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="starting")
    container_id = Column(String(128), nullable=True)
    connection_info = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    challenge = relationship("Challenge", back_populates="instances")
    user = relationship("User", back_populates="challenge_instances")

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    def mark_starting(self) -> None:
        self.status = "starting"
        self.started_at = None
        self.expires_at = None
        self.error_message = None

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
        self.expires_at = datetime.utcnow()

    def mark_stopped(self) -> None:
        self.status = "stopped"
        self.expires_at = datetime.utcnow()

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES and not self.is_expired()

    def is_expired(self, *, at: Optional[datetime] = None) -> bool:
        if self.expires_at is None:
            return False
        pivot = at or datetime.utcnow()
        expires = self._naive_utc(self.expires_at)
        return bool(expires and expires < self._naive_utc(pivot))
