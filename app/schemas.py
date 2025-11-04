# app/schemas.py
# ------------------------------------------------------------
# Pydantic v2 schemas, organized by domain
# ------------------------------------------------------------
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr, ConfigDict


# ============================================================
# Users
# ============================================================

class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    created_at: datetime


class UserProfileRead(UserProfile):
    display_name: Optional[str] = None
    bio: Optional[str] = None


class UserProfileUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    display_name: Optional[str] = None
    bio: Optional[str] = None


# ============================================================
# Teams
# ============================================================

class TeamCreate(BaseModel):
    name: str


class TeamReadPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # raw DB name (not shown to users directly)
    team_name: str
    created_by: int
    created_at: datetime
    competition_id: Optional[int] = None
    is_deleted: bool = False
    leader_id: Optional[int] = None

    # convenience for UIs
    def display_name(self) -> str:
        return f"Deleted Team #{self.id}" if self.is_deleted else (self.team_name or "Unnamed Team")


class TeamReadAdmin(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    team_name: str
    created_by: int
    created_at: datetime
    competition_id: Optional[int] = None
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None
    deleted_by_user_id: Optional[int] = None
    leader_id: Optional[int] = None


# ============================================================
# Challenges (tags, hints, CRUD)
# ============================================================

# ---- Hints ----
class HintCreate(BaseModel):
    text: str
    penalty: int = 0
    order_index: int = 0


class HintRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    penalty: int
    order_index: int


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: Optional[str] = None
    url: Optional[str] = None
    filesize: Optional[int] = None


class ChallengeInstanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    container_id: Optional[str] = None
    connection_info: Optional[dict] = None
    started_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    error_message: Optional[str] = None
    access_url: Optional[str] = None


# ---- Challenge base / create / update ----
class ChallengeBase(BaseModel):
    title: str
    description: str
    category_id: int
    # static points kept for now; dynamic scoring can override at submission time
    points: int
    difficulty: Optional[str] = "easy"
    docker_image: Optional[str] = None
    competition_id: Optional[int] = None
    unlocked_by_id: Optional[int] = None
    # tags as simple strings stored via ChallengeTag rows
    tags: List[str] = []
    # optional visibility controls (match your model defaults)
    is_active: Optional[bool] = True
    is_private: Optional[bool] = False
    visible_from: Optional[datetime] = None
    visible_to: Optional[datetime] = None


class ChallengeCreate(ChallengeBase):
    # keep flag in write-only create model; do NOT expose in reads
    flag: str
    # nested hints
    hints: List[HintCreate] = []


class ChallengeUpdate(BaseModel):
    # all optional; partial updates supported
    title: Optional[str] = None
    description: Optional[str] = None
    category_id: Optional[int] = None
    points: Optional[int] = None
    difficulty: Optional[str] = None
    docker_image: Optional[str] = None
    competition_id: Optional[int] = None
    unlocked_by_id: Optional[int] = None
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None
    is_private: Optional[bool] = None
    visible_from: Optional[datetime] = None
    visible_to: Optional[datetime] = None
    # allow full replacement of hints if provided
    hints: Optional[List[HintCreate]] = None
    # allow updating flag (write-only). Don’t mirror back in any read model.
    flag: Optional[str] = None


# ---- Public/Admin read models (no flag exposure) ----
class ChallengePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    category_id: int
    points: int
    difficulty: Optional[str] = None
    created_at: datetime
    competition_id: Optional[int] = None
    unlocked_by_id: Optional[int] = None
    is_active: bool
    is_private: bool
    visible_from: Optional[datetime] = None
    visible_to: Optional[datetime] = None
    # derived / related
    tags: List[str] = []
    hints: List[HintRead] = []
    attachments: List[AttachmentRead] = []
    active_instance: Optional[ChallengeInstanceRead] = None
    access_url: Optional[str] = None
    solves_count: int = 0  # fill in route from related table


class ChallengeAdmin(BaseModel):
    """
    Same as public, but reserved for future admin-only fields
    (we still do NOT expose the flag here).
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    category_id: int
    points: int
    difficulty: Optional[str] = None
    created_at: datetime
    competition_id: Optional[int] = None
    unlocked_by_id: Optional[int] = None
    is_active: bool
    is_private: bool
    visible_from: Optional[datetime] = None
    visible_to: Optional[datetime] = None
    tags: List[str] = []
    hints: List[HintRead] = []
    attachments: List[AttachmentRead] = []
    active_instance: Optional[ChallengeInstanceRead] = None
    access_url: Optional[str] = None
    solves_count: int = 0


# ============================================================
# Submissions
# ============================================================

class FlagSubmission(BaseModel):
    challenge_id: int
    submitted_flag: str
    # optional: capture revealed hints to calculate penalties at submit time
    used_hint_ids: Optional[List[int]] = None


class SubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    challenge_id: int
    submitted_hash: str
    is_correct: bool
    submitted_at: datetime
    first_blood: bool | None = None
    points_awarded: int | None = None
    used_hint_ids: str | None = None  


class SubmissionResult(BaseModel):
    correct: bool
    message: str
    score: int


# ============================================================
# Competitions
# ============================================================

class CompetitionCreate(BaseModel):
    name: str


class CompetitionOut(CompetitionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int

# --- Achievements ---
class AchievementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    type: str
    challenge_id: int | None = None
    category_id: int | None = None
    details: str | None = None
    points_at_award: int | None = None
    awarded_at: datetime

