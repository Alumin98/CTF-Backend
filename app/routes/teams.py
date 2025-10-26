# app/routes/teams.py

from datetime import datetime, timezone
import logging
import traceback
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_token import get_current_user
from app.database import get_db
from app.models.submission import Submission
from app.models.team import Team
from app.models.user import User
from app.schemas import TeamCreate, TeamReadPublic, TeamReadAdmin, UserProfile

logger = logging.getLogger("teams")

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def is_admin(user) -> bool:
    return getattr(user, "role", None) == "admin"

def is_leader(user, team: Team) -> bool:
    return hasattr(team, "leader_id") and team.leader_id == getattr(user, "id", None)

async def team_has_participated(db: AsyncSession, team_id: int) -> bool:
    """A team has 'participated' if any member submitted or it's linked to a competition."""
    sub_count = (
        await db.execute(
            select(func.count(Submission.id))
            .select_from(Submission)
            .join(User, User.id == Submission.user_id)
            .where(User.team_id == team_id)
        )
    ).scalar_one() or 0

    comp_id = (
        await db.execute(select(Team.competition_id).where(Team.id == team_id))
    ).scalar_one_or_none()

    return sub_count > 0 or comp_id is not None

async def ensure_can_delete_team(db: AsyncSession, team: Team, user: User) -> None:
    """
    Deletion rules:
    - Admins can delete any team.
    - Current leader can delete only if the team has NOT participated.
    - Original creator has NO delete privilege once leadership is transferred.
    """
    if is_admin(user):
        return

    if not is_leader(user, team):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the current team leader or an admin can delete this team."
        )

    if await team_has_participated(db, team.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Team cannot be deleted after participation (admin required)."
        )

# -------------------------------------------------------------------
# Router
# -------------------------------------------------------------------

router = APIRouter(tags=["Teams"])

# Create team --------------------------------------------------------

@router.post("/teams/", response_model=TeamReadPublic)
async def create_team(
    team: TeamCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Unique name
    exists = await db.scalar(select(Team.id).where(Team.team_name == team.name))
    if exists:
        raise HTTPException(status_code=400, detail="Team name already exists")

    # Create team; creator is initial leader
    new_team = Team(team_name=team.name, created_by=user.id, leader_id=user.id)
    db.add(new_team)
    await db.flush()  # populate new_team.id

    # Attach creator to team
    db_user = await db.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    db_user.team_id = new_team.id

    await db.commit()
    await db.refresh(new_team)
    return new_team

# List teams ---------------------------------------------------------

@router.get("/teams/", response_model=List[TeamReadPublic])
async def list_teams(
    db: AsyncSession = Depends(get_db),
    include_deleted: bool = False
):
    stmt = select(Team)
    if not include_deleted:
        stmt = stmt.where(Team.is_deleted == False)
    teams = (await db.execute(stmt)).scalars().all()
    return teams

# Join team (self-healing) ------------------------------------------

@router.post("/teams/{team_id}/join")
async def join_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # Target team must exist and not be deleted
        team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        if getattr(team, "is_deleted", False):
            raise HTTPException(status_code=400, detail="Team is deleted.")

        # Load user fresh
        db_user = (await db.execute(select(User).where(User.id == current_user.id))).scalar_one_or_none()
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Auto-clear dangling membership (deleted/missing team)
        if db_user.team_id is not None:
            current_team = await db.get(Team, db_user.team_id)
            if current_team is None or getattr(current_team, "is_deleted", False):
                db_user.team_id = None
                await db.flush()
            else:
                if db_user.team_id == team_id:
                    return {"message": "Already a member of this team."}
                raise HTTPException(status_code=400, detail="Already in a team.")

        # Join
        db_user.team_id = team_id
        await db.commit()
        await db.refresh(db_user)
        return {"message": f"Joined team {team.team_name}"}

    except HTTPException:
        raise
    except Exception:
        logger.error("Error joining team", exc_info=True)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Join team failed.")

# Team members -------------------------------------------------------

@router.get("/teams/{team_id}/members", response_model=List[UserProfile])
async def get_team_members(
    team_id: int,
    db: AsyncSession = Depends(get_db)
):
    team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if getattr(team, "is_deleted", False):
        return []  # or raise HTTPException(status_code=404, detail="Team deleted")

    result = await db.execute(select(User).where(User.team_id == team_id))
    return result.scalars().all()

# Delete team (soft-delete + bulk detach) ---------------------------

@router.delete("/teams/{team_id}", status_code=204)
async def delete_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    await ensure_can_delete_team(db, team, user)

    # Bulk detach all members
    await db.execute(
        update(User)
        .where(User.team_id == team_id)
        .values(team_id=None)
    )

    # Soft delete + free name; clear leader_id to avoid dangling references
    team.team_name = f"deleted-team-{team.id}"
    team.is_deleted = True
    team.deleted_at = datetime.now(timezone.utc)
    team.deleted_by_user_id = user.id
    team.leader_id = None

    await db.commit()
    return

# Admin list (all teams, including deleted) -------------------------

@router.get("/admin/teams/", response_model=List[TeamReadAdmin])
async def admin_list_teams(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")
    teams = (await db.execute(select(Team))).scalars().all()
    return teams

# Leave current team -------------------------------------------------

@router.post("/leave", summary="Leave your current team")
async def leave_team(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Must be in a team
    if current_user.team_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are not currently in a team.",
        )

    team = await db.get(Team, current_user.team_id)
    if team is None:
        # Dangling link cleanup
        current_user.team_id = None
        await db.commit()
        return {"detail": "You were linked to a non-existent team. Link cleared."}

    # Count members BEFORE detaching
    members_count = await db.scalar(
        select(func.count(User.id)).where(User.team_id == team.id)
    ) or 0

    # Leaders cannot leave while others remain
    if hasattr(team, "leader_id") and team.leader_id == current_user.id and members_count > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Team leaders cannot leave while other members remain. "
                "Transfer leadership to another member or delete the team."
            ),
        )

    # Detach the user
    current_user.team_id = None
    await db.flush()

    # If last member, hard-delete team row
    if members_count - 1 <= 0:
        await db.delete(team)

    await db.commit()
    return {"detail": "You have left the team."}

# Transfer leadership -----------------------------------------------

@router.post("/{team_id}/transfer-leadership/{new_leader_user_id}",
             summary="Transfer team leadership to another member")
async def transfer_leadership(
    team_id: int,
    new_leader_user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")

    if not hasattr(team, "leader_id"):
        raise HTTPException(
            status_code=400,
            detail="Leadership is not supported for this team model."
        )

    # Only current leader or admin may transfer
    if not (is_admin(current_user) or is_leader(current_user, team)):
        raise HTTPException(status_code=403, detail="Only the current team leader or an admin can transfer leadership.")

    new_leader = await db.get(User, new_leader_user_id)
    if not new_leader or new_leader.team_id != team.id:
        raise HTTPException(status_code=400, detail="New leader must be a current member of this team.")

    team.leader_id = new_leader_user_id
    await db.commit()
    return {"detail": "Leadership transferred."}
