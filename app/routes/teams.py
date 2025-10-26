from datetime import datetime, timezone
import logging
import traceback

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
async def create_team(
    team: TeamCreate,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    # duplicate name check
    exists = await db.scalar(select(Team.id).where(Team.team_name == team.name))
    if exists:
        raise HTTPException(status_code=400, detail="Team name already exists")

    # create team, make creator leader
    new_team = Team(team_name=team.name, created_by=user.id, leader_id=user.id)
    db.add(new_team)
    await db.flush()  # get new_team.id

    # attach a managed instance before updating
    db_user = await db.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    db_user.team_id = new_team.id

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
    try:
        # 1) Target team must exist and not be deleted
        team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        if getattr(team, "is_deleted", False):
            raise HTTPException(status_code=400, detail="Team is deleted.")

        # 2) Load the user fresh from DB
        db_user = (await db.execute(select(User).where(User.id == current_user.id))).scalar_one_or_none()
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")

        # 3) Auto-clear dangling membership (team deleted or missing)
        if db_user.team_id is not None:
            current_team = await db.get(Team, db_user.team_id)
            if current_team is None or getattr(current_team, "is_deleted", False):
                # Heal the stale link and continue
                db_user.team_id = None
                await db.flush()
            else:
                if db_user.team_id == team_id:
                    return {"message": "Already a member of this team."}
                raise HTTPException(status_code=400, detail="Already in a team.")

        # 4) Join
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



@router.get("/teams/{team_id}/members", response_model=list[UserProfile])
async def get_team_members(team_id: int, db: AsyncSession = Depends(get_db)):
    team_res = await db.execute(select(Team).where(Team.id == team_id))
    team = team_res.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if getattr(team, "is_deleted", False):
        return []  # or raise HTTPException(404, "Team deleted")

    result = await db.execute(select(User).where(User.team_id == team_id))
    return result.scalars().all()

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

    # Ensure no one remains linked to this team (robust bulk update)
    # Also clear leader relationship to avoid dangling FK references
    team.leader_id = None
    await db.execute(
        update(User)
        .where(User.team_id == team_id)
        .values(team_id=None)
    )

    await db.commit()
    return

@router.get("/admin/teams/", response_model=list[TeamReadAdmin])
async def admin_list_teams(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    teams = (await db.execute(select(Team))).scalars().all()
    return teams

@router.post("/leave", tags=["Teams"], summary="Leave your current team")
async def leave_team(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1) Must be in a team
    if current_user.team_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are not currently in a team.",
        )

    # 2) Load team; if dangling, just clear link
    team = await db.get(Team, current_user.team_id)
    if team is None:
        current_user.team_id = None
        await db.commit()
        return {"detail": "You were linked to a non-existent team. Link cleared."}

    # 3) Count members BEFORE detaching
    members_count = await db.scalar(
        select(func.count(User.id)).where(User.team_id == team.id)
    ) or 0

    # 4) OPTIONAL leader rule — enforced only if Team has leader_id
    if hasattr(team, "leader_id") and team.leader_id == current_user.id and members_count > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Team leaders cannot leave while other members remain. "
                "Transfer leadership to another member or delete the team."
            ),
        )

    # 5) Detach the user
    current_user.team_id = None
    await db.flush()

    # 6) If last member, delete team
    if members_count - 1 <= 0:
        await db.delete(team)

    await db.commit()
    return {"detail": "You have left the team."}

@router.post("/{team_id}/transfer-leadership/{new_leader_user_id}",
             tags=["Teams"], summary="Transfer team leadership to another member")
async def transfer_leadership(
    team_id: int,
    new_leader_user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")

    # If no leader concept on Team, this is not supported
    if not hasattr(team, "leader_id"):
        raise HTTPException(
            status_code=400,
            detail="Leadership is not supported for this team model."
        )

    # Only current leader or admin may transfer
    if not is_admin(current_user) and team.leader_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the team leader or an admin can transfer leadership.")

    new_leader = await db.get(User, new_leader_user_id)
    if not new_leader or new_leader.team_id != team.id:
        raise HTTPException(status_code=400, detail="New leader must be a current member of this team.")

    team.leader_id = new_leader_user_id
    await db.commit()
    return {"detail": "Leadership transferred."}
