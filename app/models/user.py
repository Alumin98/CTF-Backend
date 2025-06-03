from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True)
    password_hash = Column("hashed_password", String, nullable=False)
    role = Column(String, default='player')
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)

    created_at = Column(DateTime, default=func.now())