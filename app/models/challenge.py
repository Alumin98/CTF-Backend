from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, DateTime, func
from app.database import Base

class Challenge(Base):
    __tablename__ = "challenges"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=False)
    description = Column(Text)
    category_id = Column(Integer, ForeignKey("categories.id"))
    flag = Column(String(255))
    points = Column(Integer)
    difficulty = Column(String(20))  # easy/medium/hard
    docker_image = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
