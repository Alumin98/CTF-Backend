from sqlalchemy import Column, Integer, String
from app.database import Base

class Competition(Base):
    __tablename__ = "competitions"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
