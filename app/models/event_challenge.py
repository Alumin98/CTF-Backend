from sqlalchemy import Column, Integer, ForeignKey
from app.database import Base

class EventChallenge(Base):
    __tablename__ = "event_challenges"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    challenge_id = Column(Integer, ForeignKey("challenges.id"), nullable=False)
