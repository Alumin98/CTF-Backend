from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.future import select
from app.models.team import Team
from app.models.user import User
from app.database import get_db
from app.schemas import TeamCreate, TeamRead, UserProfile
from app.auth_token import get_current_user

router = APIRouter()


@router.post("/teams/", response_model=TeamRead)
async def create_team(team: TeamCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    result = db.execute(select(Team).where(Team.team_name == team.name))
    if result.scalar():
        raise HTTPException(status_code=400, detail="Team name already exists")

    new_team = Team(team_name=team.name, created_by=user.id)
    db.add(new_team)
    db.commit()
    db.refresh(new_team)
    return new_team



@router.get("/teams/", response_model=list[TeamRead])
async def list_teams(db: Session = Depends(get_db)):
    result =  db.execute(select(Team))
    teams = result.scalars().all()
    return teams


@router.post("/teams/{team_id}/join")
async def join_team(
    team_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # Make sure team exists
    result =  db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Update current user's team
    current_user.team_id = team_id
    db.commit()

    return {"message": f"Joined team {team.team_name}"}



from app.schemas import UserProfile
  # we'll add this next

@router.get("/teams/{team_id}/members", response_model=list[UserProfile])
async def get_team_members(team_id: int, db: Session = Depends(get_db)):
    result =  db.execute(select(User).where(User.team_id == team_id))
    members = result.scalars().all()
    return members



