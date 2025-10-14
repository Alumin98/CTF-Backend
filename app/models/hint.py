from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship, reconstructor

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

    _order_index_runtime = None

    def __init__(self, *args, order_index: int | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if order_index is not None:
            self.order_index = order_index
        else:
            self._order_index_runtime = None

    @reconstructor
    def _init_on_load(self) -> None:
        self._order_index_runtime = None

    @property
    def order_index(self) -> int:
        if self._order_index_runtime is not None:
            return self._order_index_runtime
        return getattr(self, "id", 0) or 0

    @order_index.setter
    def order_index(self, value: int) -> None:
        try:
            self._order_index_runtime = int(value)
        except (TypeError, ValueError):
            self._order_index_runtime = 0

    challenge = relationship("Challenge", back_populates="hints")
