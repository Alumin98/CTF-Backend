from fastapi import FastAPI
from app.database import Base, engine
from app.models import * 


app = FastAPI()

# Auto-create all tables in the DB on startup
Base.metadata.create_all(bind=engine)
