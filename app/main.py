from fastapi import FastAPI
from app.database import Base, engine


from app.models import user

app = FastAPI()


Base.metadata.create_all(bind=engine)