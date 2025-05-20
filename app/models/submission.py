from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, func, select
from app.database import Base

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    challenge_id = Column(Integer, ForeignKey("challenges.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    submitted_flag = Column(String, nullable=False)
    is_correct = Column(Boolean, nullable=False)  # Changed to Boolean
    submitted_at = Column(DateTime, default=func.now())


def check_existing_correct_submission(db, user_id: int, challenge_id: int):
    stmt = select(Submission).where(
        Submission.user_id == user_id,
        Submission.challenge_id == challenge_id,
        Submission.is_correct == true  
    )
    result = db.execute(stmt).first()
    return result
