from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.competition import Competition
from app.schemas import CompetitionCreate, CompetitionOut
router = APIRouter(prefix="/competitions", tags=["competitions"])

@router.post("/", response_model=CompetitionOut)
async def create_competition(
    comp: CompetitionCreate, db: AsyncSession = Depends(get_db)
):
    db_comp = Competition(**comp.dict())
    db.add(db_comp)
    await db.commit()
    await db.refresh(db_comp)
    return db_comp

@router.get("/", response_model=list[CompetitionOut])
async def get_all(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Competition))
    return result.scalars().all()

@router.get("/{id}", response_model=CompetitionOut)
async def get_by_id(id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Competition).where(Competition.id == id))
    comp = result.scalars().first()
    if not comp:
        raise HTTPException(404, "Competition not found")
    return comp

@router.delete("/{id}")
async def delete_competition(id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Competition).where(Competition.id == id))
    comp = result.scalars().first()
    if not comp:
        raise HTTPException(404, "Competition not found")
    await db.delete(comp)
    await db.commit()
    return {"message": "Deleted"}
