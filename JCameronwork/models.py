from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Boolean

from datetime import datetime


from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship



# ⬇️ Base class from SQLAlchemy to make all your tables inherit from
Base = declarative_base()

class User(Base):
    __tablename__ = "users"  # ⬅️ name of the SQL table

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    role = Column(String, default="player")  # 'admin' or 'player'


    #TEAMS
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    team = relationship("Team", back_populates="members")



class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    members = relationship("User", back_populates="team")





class Challenge(Base):
    __tablename__ = "challenges"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String, nullable=False)
    points = Column(Integer, default=100)
    flag = Column(String, nullable=False)  # secret flag string
    created_at = Column(DateTime, default=datetime.utcnow)



class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    challenge_id = Column(Integer, ForeignKey("challenges.id"))
    submitted_flag = Column(String, nullable=False)
    is_correct = Column(Boolean, default=False)
    submitted_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    challenge = relationship("Challenge")


