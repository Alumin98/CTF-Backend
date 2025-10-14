from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text as sql_text

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
    text = Column("hint_text", Text, nullable=False)
    penalty = Column("point_penalty", Integer, nullable=False, default=0)
    order_index = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )

    challenge = relationship("Challenge", back_populates="hints")
