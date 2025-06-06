from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from app.database import Base

class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    team_name = Column(String(100), unique=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    competition_id = Column(Integer, ForeignKey("competitions.id"))

