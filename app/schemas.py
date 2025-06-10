from datetime import datetime
from pydantic import BaseModel, EmailStr

class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserProfile(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True

class TeamCreate(BaseModel):
    name: str

class TeamRead(BaseModel):
    id: int
    team_name: str
    created_at: datetime

    class Config:
        from_attributes = True 

#UPDATED
class ChallengeCreate(BaseModel):
    title: str
    description: str
    category_id: int
    points: int
    flag: str
    unlocked_by_id: int | None = None
    difficulty: str | None = None
    docker_image: str | None = None
    competition_id: int | None = None

#UPDATED
class ChallengePublic(BaseModel):
    id: int
    title: str
    description: str
    category_id: int
    points: int
    created_at: datetime
    unlocked_by_id: int | None = None  

    class Config:
        from_attributes = True

class FlagSubmission(BaseModel):
    challenge_id: int
    submitted_flag: str

class SubmissionRead(BaseModel):
    id: int
    user_id: int
    challenge_id: int
    submitted_hash: str
    is_correct: bool  
    submitted_at: datetime

    class Config:
        from_attributes = True

class SubmissionResult(BaseModel):
    correct: bool
    message: str
    score: int


class CompetitionCreate(BaseModel):
    name: str

class CompetitionOut(CompetitionCreate):
    id: int

    class Config:
        from_attributes = True