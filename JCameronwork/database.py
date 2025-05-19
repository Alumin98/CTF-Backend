import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from models import Base

# ⬇️ load the .env file so DATABASE_URL is available
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")

# ⬇️ create the SQLAlchemy engine for async DB access
engine = create_async_engine(DATABASE_URL, echo=True)

# ⬇️ set up session factory
SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# ⬇️ use this to create the DB tables (just for dev with SQLite)
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# ⬇️ this will be used by FastAPI to get a DB session
async def get_db():
    async with SessionLocal() as session:
        yield session

        