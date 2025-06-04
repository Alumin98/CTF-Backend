from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.competition import Competition
from app.schemas.competition import CompetitionCreate, CompetitionOut

router = APIRouter(prefix="/competitions", tags=["competitions"])

@router.post("/", response_model=CompetitionOut)
def create_competition(comp: CompetitionCreate, db: Session = Depends(get_db)):
    db_comp = Competition(**comp.dict())
    db.add(db_comp)
    db.commit()
    db.refresh(db_comp)
    return db_comp

@router.get("/", response_model=list[CompetitionOut])
def get_all(db: Session = Depends(get_db)):
    return db.query(Competition).all()

@router.get("/{id}", response_model=CompetitionOut)
def get_by_id(id: int, db: Session = Depends(get_db)):
    comp = db.query(Competition).filter_by(id=id).first()
    if not comp:
        raise HTTPException(404, "Competition not found")
    return comp

@router.delete("/{id}")
def delete_competition(id: int, db: Session = Depends(get_db)):
    comp = db.query(Competition).filter_by(id=id).first()
    if not comp:
        raise HTTPException(404, "Competition not found")
    db.delete(comp)
    db.commit()
    return {"message": "Deleted"}
