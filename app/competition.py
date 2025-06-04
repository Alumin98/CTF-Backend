from pydantic import BaseModel

class CompetitionCreate(BaseModel):
    name: str

class CompetitionOut(CompetitionCreate):
    id: int

    class Config:
        orm_mode = True

