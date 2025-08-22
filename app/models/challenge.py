from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, DateTime, func
from app.database import Base

class Challenge(Base):
    __tablename__ = "challenges"

    id = Column(Integer, primary_key=True, index=True)  # ✅ MUST HAVE THIS
    title = Column(String(100), nullable=False)
    description = Column(Text)
    category_id = Column(Integer, ForeignKey("categories.id"))
    flag = Column(String(255))
    points = Column(Integer)
    difficulty = Column(String(20), nullable=True, default='easy')
    docker_image = Column(String(255), nullable=True)
    is_active  = Column(Boolean, nullable=False, server_default="true")
    is_private = Column(Boolean, nullable=False, server_default="false")
    visible_from = Column(DateTime, nullable=True)
    visible_to = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=True)
    unlocked_by_id = Column(Integer, ForeignKey("challenges.id"), nullable=True)  # ✅ recently added
