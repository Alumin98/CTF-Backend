from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy import Column, Integer, Text, ForeignKey, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import NoSuchTableError, SQLAlchemyError
from sqlalchemy.orm import relationship

from app.database import Base, engine


DEFAULT_TEXT_COLUMN = "text"
DEFAULT_PENALTY_COLUMN = "penalty"


def _detect_hint_columns(sync_engine: Optional[Engine]) -> Tuple[str, str]:
    """Determine the column names backing Hint.text/penalty.

    Legacy databases used ``hint_text``/``point_penalty`` while newer
    deployments expose ``text``/``penalty``. We inspect the bound engine (when
    available) so the ORM can match whichever schema exists without rewriting
    tables at runtime.
    """

    if sync_engine is None:
        return DEFAULT_TEXT_COLUMN, DEFAULT_PENALTY_COLUMN

    try:
        with sync_engine.connect() as conn:
            inspector = inspect(conn)
            try:
                columns = inspector.get_columns("hints")
            except NoSuchTableError:
                return DEFAULT_TEXT_COLUMN, DEFAULT_PENALTY_COLUMN
    except SQLAlchemyError:
        return DEFAULT_TEXT_COLUMN, DEFAULT_PENALTY_COLUMN
    except Exception:
        return DEFAULT_TEXT_COLUMN, DEFAULT_PENALTY_COLUMN

    names = {col["name"] for col in columns}

    text_column = "hint_text" if "hint_text" in names else DEFAULT_TEXT_COLUMN
    penalty_column = (
        "point_penalty" if "point_penalty" in names else DEFAULT_PENALTY_COLUMN
    )

    return text_column, penalty_column


_TEXT_COLUMN, _PENALTY_COLUMN = _detect_hint_columns(
    getattr(engine, "sync_engine", None)
)


class Hint(Base):
    __tablename__ = "hints"

    id = Column(Integer, primary_key=True)
    challenge_id = Column(
        Integer,
        ForeignKey("challenges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text = Column(_TEXT_COLUMN, Text, nullable=False)
    penalty = Column(_PENALTY_COLUMN, Integer, nullable=False, default=0)
    order_index = Column(Integer, nullable=False, default=0)

    challenge = relationship("Challenge", back_populates="hints")
