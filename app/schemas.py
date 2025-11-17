# app/schemas.py
# ------------------------------------------------------------
# Pydantic v2 schemas, organized by domain
# ------------------------------------------------------------
from datetime import datetime
import re
from typing import Optional, List, Sequence

from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator

from app.models.challenge import DeploymentType


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SCRIPT_TAG_RE = re.compile(r"<\s*/?\s*script", re.IGNORECASE)


def _sanitize_single_line_text(value: str | None, *, allow_empty: bool = False) -> str | None:
    if value is None:
        return value
    if not isinstance(value, str):
        raise TypeError("Expected string input")
    cleaned = _CONTROL_CHAR_RE.sub("", value).strip()
    if not allow_empty and not cleaned:
        raise ValueError("Value cannot be empty")
    if any(ch in {"\n", "\r"} for ch in cleaned):
        raise ValueError("Value must be a single line of text")
    if "<" in cleaned or ">" in cleaned:
        raise ValueError("HTML tags are not allowed in this field")
    if _SCRIPT_TAG_RE.search(cleaned):
        raise ValueError("Script tags are not allowed")
    return cleaned


def _sanitize_multiline_text(value: str | None, *, allow_empty: bool = False) -> str | None:
    if value is None:
        return value
    if not isinstance(value, str):
        raise TypeError("Expected string input")
    cleaned = _CONTROL_CHAR_RE.sub("", value).strip()
    if not allow_empty and not cleaned:
        raise ValueError("Value cannot be empty")
    if _SCRIPT_TAG_RE.search(cleaned):
        raise ValueError("Script tags are not allowed")
    return cleaned


def _sanitize_tags(value: Sequence[str] | str | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    cleaned: list[str] = []
    for tag in value:
        sanitized = _sanitize_single_line_text(str(tag))
        if sanitized:
            cleaned.append(sanitized)
    return cleaned


# ============================================================
# Users
# ============================================================

class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def _clean_username(cls, value: str) -> str:
        return _sanitize_single_line_text(value)


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
    username: Optional[str] = Field(default=None, min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    bio: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("username", mode="before")
    @classmethod
    def _clean_optional_username(cls, value: Optional[str]) -> Optional[str]:
        return _sanitize_single_line_text(value) if value is not None else value

    @field_validator("password", mode="before")
    @classmethod
    def _clean_password(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not isinstance(value, str):
            raise TypeError("Expected string input")
        stripped = value.strip()
        return stripped or None

    @field_validator("display_name", mode="before")
    @classmethod
    def _clean_display_name(cls, value: Optional[str]) -> Optional[str]:
        return _sanitize_single_line_text(value) if value is not None else value

    @field_validator("bio", mode="before")
    @classmethod
    def _clean_bio(cls, value: Optional[str]) -> Optional[str]:
        return _sanitize_multiline_text(value, allow_empty=True) if value is not None else value


class AdminBootstrapRequest(BaseModel):
    token: str = Field(min_length=8, max_length=128)

    @field_validator("token", mode="before")
    @classmethod
    def _clean_token(cls, value: str) -> str:
        return _sanitize_single_line_text(value)


# ============================================================
# Teams
# ============================================================

class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return _sanitize_single_line_text(value)


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
    text: str = Field(min_length=1, max_length=500)
    penalty: int = 0
    order_index: int = 0

    @field_validator("text", mode="before")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        return _sanitize_multiline_text(value)


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
class CategoryBase(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: Optional[str] = Field(default=None, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return _sanitize_single_line_text(value)

    @field_validator("description", mode="before")
    @classmethod
    def _clean_description(cls, value: Optional[str]) -> Optional[str]:
        return _sanitize_multiline_text(value, allow_empty=True) if value is not None else value


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None


class ChallengeBase(BaseModel):
    title: str = Field(min_length=3, max_length=128)
    description: str = Field(min_length=1, max_length=5000)
    category_id: int
    # static points kept for now; dynamic scoring can override at submission time
    points: int = Field(ge=0, le=10000)
    difficulty: Optional[str] = Field(default="easy", max_length=32)
    docker_image: Optional[str] = Field(default=None, max_length=255)
    competition_id: Optional[int] = None
    unlocked_by_id: Optional[int] = None
    # tags as simple strings stored via ChallengeTag rows
    tags: List[str] = Field(default_factory=list)
    # optional visibility controls (match your model defaults)
    is_active: Optional[bool] = True
    is_private: Optional[bool] = False
    visible_from: Optional[datetime] = None
    visible_to: Optional[datetime] = None
    deployment_type: DeploymentType = DeploymentType.dynamic_container
    service_port: Optional[int] = None
    always_on: Optional[bool] = False

    @field_validator("title", "difficulty", "docker_image", mode="before")
    @classmethod
    def _clean_single_line_fields(cls, value: Optional[str]) -> Optional[str]:
        return _sanitize_single_line_text(value) if value is not None else value

    @field_validator("description", mode="before")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        return _sanitize_multiline_text(value)

    @field_validator("tags", mode="before")
    @classmethod
    def _clean_tags(cls, value):
        sanitized = _sanitize_tags(value)
        return sanitized or []


class ChallengeCreate(ChallengeBase):
    # keep flag in write-only create model; do NOT expose in reads
    flag: str = Field(min_length=1, max_length=256)
    # nested hints
    hints: List[HintCreate] = Field(default_factory=list)

    @field_validator("flag", mode="before")
    @classmethod
    def _clean_flag(cls, value: str) -> str:
        return _sanitize_single_line_text(value)


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
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    deployment_type: Optional[DeploymentType] = None
    service_port: Optional[int] = None
    always_on: Optional[bool] = None
    # allow full replacement of hints if provided
    hints: Optional[List[HintCreate]] = None
    # allow updating flag (write-only). Don’t mirror back in any read model.
    flag: Optional[str] = Field(default=None, min_length=1, max_length=256)

    @field_validator("title", "difficulty", "docker_image", mode="before")
    @classmethod
    def _clean_optional_single_line_fields(cls, value: Optional[str]) -> Optional[str]:
        return _sanitize_single_line_text(value) if value is not None else value

    @field_validator("description", mode="before")
    @classmethod
    def _clean_optional_description(cls, value: Optional[str]) -> Optional[str]:
        return _sanitize_multiline_text(value) if value is not None else value

    @field_validator("flag", mode="before")
    @classmethod
    def _clean_flag(cls, value: Optional[str]) -> Optional[str]:
        return _sanitize_single_line_text(value) if value is not None else value

    @field_validator("tags", mode="before")
    @classmethod
    def _clean_tags(cls, value):
        return _sanitize_tags(value)


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
    deployment_type: DeploymentType
    service_port: Optional[int] = None
    always_on: bool
    # derived / related
    tags: List[str] = Field(default_factory=list)
    hints: List[HintRead] = Field(default_factory=list)
    attachments: List[AttachmentRead] = Field(default_factory=list)
    active_instance: Optional[ChallengeInstanceRead] = None
    access_url: Optional[str] = None
    solves_count: int = 0
    solves_count: int = 0  # fill in route from related table


class ChallengeAdmin(BaseModel):
    """Admin-facing challenge details, including the stored flag hash."""
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
    deployment_type: DeploymentType
    service_port: Optional[int] = None
    always_on: bool
    tags: List[str] = Field(default_factory=list)
    hints: List[HintRead] = Field(default_factory=list)
    attachments: List[AttachmentRead] = Field(default_factory=list)
    active_instance: Optional[ChallengeInstanceRead] = None
    access_url: Optional[str] = None
    solves_count: int = 0
    flag_hash: Optional[str] = None


# ============================================================
# Submissions
# ============================================================

class FlagSubmission(BaseModel):
    challenge_id: int
    submitted_flag: str = Field(min_length=1, max_length=256)
    # optional: capture revealed hints to calculate penalties at submit time
    used_hint_ids: Optional[List[int]] = None

    @field_validator("submitted_flag", mode="before")
    @classmethod
    def _clean_flag(cls, value: str) -> str:
        return _sanitize_single_line_text(value)


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

