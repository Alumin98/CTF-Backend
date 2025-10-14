from sqlalchemy import Column, Integer, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class Hint(Base):
    __tablename__ = "hints"

    id = Column(Integer, primary_key=True)
    challenge_id = Column(
        Integer,
        ForeignKey("challenges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text = Column(Text, nullable=False)
    penalty = Column(Integer, nullable=False, default=0)
    order_index = Column(Integer, nullable=False, default=0)

    challenge = relationship("Challenge", back_populates="hints")
