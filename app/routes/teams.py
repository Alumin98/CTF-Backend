from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone
from app.models.team import Team
from app.models.user import User
from app.models.submission import Submission
from app.database import get_db
from app.schemas import TeamCreate, TeamReadPublic, TeamReadAdmin, UserProfile
from app.auth_token import get_current_user

async def team_has_participated(db: AsyncSession, team_id: int) -> bool:
    """Check if a team has any submissions or is linked to a competition."""
    # any member of this team submitted?
    q = (
        select(func.count(Submission.id))
        .select_from(Submission)
        .join(User, User.id == Submission.user_id)
        .where(User.team_id == team_id)
    )
    sub_count = (await db.execute(q)).scalar_one() or 0

    # linked to a competition?
    comp_id = (
        await db.execute(select(Team.competition_id).where(Team.id == team_id))
    ).scalar_one_or_none()

    return sub_count > 0 or comp_id is not None


def is_admin(user) -> bool:
    return getattr(user, "role", None) == "admin"


async def ensure_can_delete_team(db, team: Team, user):
    """Enforce deletion rules:
    - Admins can delete any team
    - Creator can delete only if the team has not participated
    """
    if is_admin(user):
        return
    if team.created_by != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only creator or admin can delete this team."
        )
    if await team_has_participated(db, team.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Creator cannot delete a team that has participated."
        )


router = APIRouter()

@router.post("/teams/", response_model=TeamReadPublic)
async def create_team(team: TeamCreate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(select(Team).where(Team.team_name == team.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Team name already exists")

    new_team = Team(team_name=team.name, created_by=user.id)
    db.add(new_team)
    await db.commit()
    await db.refresh(new_team)
    return new_team

@router.get("/teams/", response_model=list[TeamReadPublic])
async def list_teams(db: AsyncSession = Depends(get_db), include_deleted: bool = False):
    stmt = select(Team)
    if not include_deleted:
        stmt = stmt.where(Team.is_deleted == False)
    teams = (await db.execute(stmt)).scalars().all()
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
    

    if team.is_deleted:
        raise HTTPException(status_code=400, detail="Team is deleted.")

    # Fetch and update user in session
    user_result = await db.execute(select(User).where(User.id == current_user.id))
    db_user = user_result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if db_user.team_id == team_id:
        return {"message": "Already a member of this team."}
    if db_user.team_id is not None:
        raise HTTPException(status_code=400, detail="Already in a team.")

    db_user.team_id = team_id
    await db.commit()
    await db.refresh(db_user)

    return {"message": f"Joined team {team.team_name}"}

@router.get("/teams/{team_id}/members", response_model=list[UserProfile])
async def get_team_members(team_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.team_id == team_id))
    members = result.scalars().all()
    return members

@router.delete("/teams/{team_id}", status_code=204)
async def delete_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user)
):
    res = await db.execute(select(Team).where(Team.id == team_id))
    team = res.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    await ensure_can_delete_team(db, team, user)

    # Soft delete + rename to free the unique team_name
    team.team_name = f"deleted-team-{team.id}"
    team.is_deleted = True
    team.deleted_at = datetime.now(timezone.utc)
    team.deleted_by_user_id = user.id

    db.add(team)
    await db.commit()
    return

@router.get("/admin/teams/", response_model=list[TeamReadAdmin])
async def admin_list_teams(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    teams = (await db.execute(select(Team))).scalars().all()
    return teams
