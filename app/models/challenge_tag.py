from sqlalchemy import Column, Integer, String, ForeignKey
from app.database import Base

class ChallengeTag(Base):
    __tablename__ = "challenge_tags"

    id = Column(Integer, primary_key=True, index=True)
    challenge_id = Column(Integer, ForeignKey("challenges.id"), nullable=False)
    tag = Column(String(50), nullable=False)
