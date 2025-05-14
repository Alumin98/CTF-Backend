from sqlalchemy import Column, Integer, String, ForeignKey, Text
from app.database import Base

class Hint(Base):
    __tablename__ = "hints"

    id = Column(Integer, primary_key=True, index=True)
    challenge_id = Column(Integer, ForeignKey("challenges.id"), nullable=False)
    hint_text = Column(Text, nullable=False)
    point_penalty = Column(Integer, default=0)
