from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base

class ChallengeTag(Base):
    __tablename__ = "challenge_tags"

    id = Column(Integer, primary_key=True, index=True)
    challenge_id = Column(Integer, ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False, index=True)
    tag = Column(String(50), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("challenge_id", "tag", name="uq_challenge_tag"),
    )

    challenge = relationship("Challenge", back_populates="tags")
