from fastapi import FastAPI
from app.database import Base, engine


from app.models import user, role, team

app = FastAPI()


Base.metadata.create_all(bind=engine)