from typing import TYPE_CHECKING

from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship

from app.database import Base

# NOTE: these imports are only for type/relationship wiring; no schema changes
# Make sure these modules exist and are imported somewhere at startup so create_all sees them.
# - app/models/challenge_tag.py defines ChallengeTag with back_populates="challenge"
# - app/models/hint.py defines Hint with back_populates="challenge"
from app.models.challenge_tag import ChallengeTag  # provides .tag and challenge_id FK
from app.models.hint import Hint                   # provides text/penalty/order_index and challenge_id FK

if TYPE_CHECKING:
    from app.models.submission import Submission


class Challenge(Base):
    __tablename__ = "challenges"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=False)
    description = Column(Text)
    category_id = Column(Integer, ForeignKey("categories.id"))
    flag = Column(String(255))
    points = Column(Integer)  # keep as-is; dynamic scoring can be computed at submission time
    difficulty = Column(String(20), nullable=True, default="easy")
    docker_image = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true")
    is_private = Column(Boolean, nullable=False, server_default="false")
    visible_from = Column(DateTime, nullable=True)
    visible_to = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=True)
    unlocked_by_id = Column(Integer, ForeignKey("challenges.id"), nullable=True)  # recently added

    # --- Relationships (no schema change) ---
    # Tags (each row in challenge_tags is a single string tag for this challenge)
    tags = relationship(
        "ChallengeTag",
        back_populates="challenge",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Hints (ordered by order_index in queries/UI)
    hints = relationship(
        "Hint",
        back_populates="challenge",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    submissions = relationship("Submission", back_populates="challenge", lazy="selectin")

    # OPTIONAL: if you have a parent->children unlock chain:
    # children = relationship("Challenge", remote_side=[id])

    # --- Convenience helpers for tags as list[str] ---
    @property
    def tag_strings(self) -> list[str]:
        """Return tags as a simple list[str]."""
        return [t.tag for t in (self.tags or [])]

    def set_tag_strings(self, items: list[str]) -> None:
        """Replace all tags with a unique, case-insensitive cleaned list."""
        uniq = []
        seen = set()
        for s in (items or []):
            s2 = (s or "").strip()
            key = s2.lower()
            if s2 and key not in seen:
                uniq.append(s2)
                seen.add(key)

        # Replace in-place to keep ORM state consistent
        self.tags.clear()
        for s in uniq:
            self.tags.append(ChallengeTag(tag=s))
