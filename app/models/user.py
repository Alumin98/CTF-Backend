from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True)
    password_hash = Column("hashed_password", String, nullable=False)
    role = Column(String, default="player")
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    reset_token_hash = Column(String(64), nullable=True, index=True)
    reset_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime, default=func.now())

    team = relationship("Team", back_populates="members", foreign_keys=[team_id])

    # NEW: if user is leader of a team
    leading_team = relationship(
        "Team",
        back_populates="leader",
        uselist=False,
        foreign_keys="Team.leader_id",
    )

    # Track submissions solved by the user
    submissions = relationship(
        "Submission",
        back_populates="user",
        lazy="selectin",
    )
