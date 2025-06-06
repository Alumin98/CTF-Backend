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


class ChallengeCreate(BaseModel):
    title: str
    description: str
    category_id: int
    points: int
    flag: str

class ChallengePublic(BaseModel):
    id: int
    title: str
    description: str
    category_id: int
    points: int
    created_at: datetime

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


