from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.database import get_db
from app.auth_token import require_admin
from app.routes.auth import hash_flag

from app.models.challenge import Challenge
from app.models.submission import Submission
from app.models.user import User
from app.models.team import Team
from app.models.hint import Hint

from app.schemas import ChallengeCreate, ChallengePublic

router = APIRouter()

# If you have a real dependency, wire it in; otherwise keep it permissive.
def get_current_user():
    return None


@router.post("/challenges/", response_model=ChallengePublic)
async def create_challenge(
    challenge: ChallengeCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    try:
        data = challenge.dict()

        # Map fields + hash flag
        data["flag"] = hash_flag(challenge.flag) if challenge.flag is not None else None
        data["visible_from"] = data.pop("start_time", None)
        data["visible_to"] = data.pop("end_time", None)

        # Pull relationship inputs out BEFORE constructing the model
        tags = data.pop("tags", None)
        hints = data.pop("hints", None)

        new_ch = Challenge(**data)

        # Apply hints
        if hints:
            for h in hints:
                new_ch.hints.append(
                    Hint(text=h["text"], penalty=h["penalty"], order_index=h["order_index"])
                    if isinstance(h, dict)
                    else Hint(text=h.text, penalty=h.penalty, order_index=h.order_index)
                )

        # Apply tags (if your model has this helper)
        if tags:
            new_ch.set_tag_strings(tags)

        db.add(new_ch)
        await db.commit()
        await db.refresh(new_ch)

        return ChallengePublic(
            id=new_ch.id,
            title=new_ch.title,
            description=new_ch.description,
            category_id=getattr(new_ch, "category_id", None),
            points=new_ch.points,
            difficulty=new_ch.difficulty,
            is_active=new_ch.is_active,
            start_time=new_ch.visible_from,
            end_time=new_ch.visible_to,
            created_at=getattr(new_ch, "created_at", None),
            solves=0,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/challenges/", response_model=list[ChallengePublic])
async def list_challenges(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    """
    Return active challenges whose time window includes 'now'.
    Model uses visible_from/visible_to; API uses start_time/end_time.
    """
    res = await db.execute(select(Challenge))
    rows = res.scalars().all()

    now = datetime.now(timezone.utc)

    def to_aware(dt):
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    visible: list[ChallengePublic] = []
    for c in rows:
        if not c.is_active:
            continue

        st = to_aware(getattr(c, "visible_from", None))
        et = to_aware(getattr(c, "visible_to", None))

        if st and now < st:
            continue
        if et and now > et:
            continue

        visible.append(
            ChallengePublic(
                id=c.id,
                title=c.title,
                description=c.description,
                category_id=getattr(c, "category_id", None),
                points=c.points,
                difficulty=c.difficulty,
                is_active=c.is_active,
                start_time=st,
                end_time=et,
                created_at=getattr(c, "created_at", None),
                solves=0,
            )
        )
    return visible


@router.patch("/challenges/{challenge_id}", response_model=ChallengePublic)
async def update_challenge(
    challenge_id: int,
    challenge_update: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Challenge not found")

    # Map API -> model where needed
    if "flag" in challenge_update:
        challenge_update["flag"] = hash_flag(challenge_update["flag"])
    if "start_time" in challenge_update:
        challenge_update["visible_from"] = challenge_update.pop("start_time")
    if "end_time" in challenge_update:
        challenge_update["visible_to"] = challenge_update.pop("end_time")

    for k, v in challenge_update.items():
        setattr(ch, k, v)

    await db.commit()
    await db.refresh(ch)

    return ChallengePublic(
        id=ch.id,
        title=ch.title,
        description=ch.description,
        category_id=getattr(ch, "category_id", None),
        points=ch.points,
        difficulty=ch.difficulty,
        is_active=ch.is_active,
        start_time=getattr(ch, "visible_from", None),
        end_time=getattr(ch, "visible_to", None),
        created_at=getattr(ch, "created_at", None),
        solves=0,
    )


@router.delete("/challenges/{challenge_id}", status_code=204)
async def delete_challenge(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
):
    result = await db.execute(select(Challenge).where(Challenge.id == challenge_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Challenge not found")
    await db.delete(ch)
    await db.commit()
    return None


@router.get("/challenges/{challenge_id}/solvers")
async def get_challenge_solvers(
    challenge_id: int,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Submission, User, Team)
        .join(User, Submission.user_id == User.id)
        .join(Team, User.team_id == Team.id, isouter=True)
        .where(Submission.challenge_id == challenge_id, Submission.is_correct == True)
        .order_by(Submission.submitted_at)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "team": team.team_name if team else None,
            "user": user.username,
            "timestamp": submission.submitted_at.isoformat(),
            "first_blood": getattr(submission, "first_blood", False),
        }
        for submission, user, team in rows
    ]
