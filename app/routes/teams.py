from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.team import Team
from app.models.user import User
from app.database import get_db
from app.schemas import TeamCreate, TeamRead, UserProfile
from app.auth_token import get_current_user

router = APIRouter()

@router.post("/teams/", response_model=TeamRead)
async def create_team(team: TeamCreate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(select(Team).where(Team.team_name == team.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Team name already exists")

    new_team = Team(team_name=team.name, created_by=user.id)
    db.add(new_team)
    await db.commit()
    await db.refresh(new_team)
    return new_team

@router.get("/teams/", response_model=list[TeamRead])
async def list_teams(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Team))
    teams = (await result.scalars()).all()
    return teams

@router.post("/teams/{team_id}/join")
async def join_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # Make sure team exists
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Fetch and update user in session
    user_result = await db.execute(select(User).where(User.id == current_user.id))
    db_user = user_result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    db_user.team_id = team_id
    await db.commit()
    await db.refresh(db_user)

    return {"message": f"Joined team {team.team_name}"}

@router.get("/teams/{team_id}/members", response_model=list[UserProfile])
async def get_team_members(team_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.team_id == team_id))
    members = (await result.scalars()).all()
    return members
