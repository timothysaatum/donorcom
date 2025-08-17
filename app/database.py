# from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
# from app.db.base import Base
# from app.config import settings
# from sqlalchemy import create_engine
# from sqlalchemy.orm import sessionmaker
# import logging


# # Convert sync SQLite URL to async-compatible one
# SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

# # Create async engine
# engine = create_async_engine(
#     SQLALCHEMY_DATABASE_URL,
#     connect_args={"check_same_thread": False},
#     echo=True,
# )

# # Create session factory for async sessions
# async_session = async_sessionmaker(
#     bind=engine,
#     class_=AsyncSession,
#     expire_on_commit=False,
# )



# SYNC_DATABASE_URL = settings.DATABASE_URL

# sync_engine = create_engine(
#     SYNC_DATABASE_URL,
#     connect_args={"check_same_thread": False},
#     echo=True
# )

# SyncSessionLocal = sessionmaker(bind=sync_engine)

# # Import models to register with Base
# from app.models.user import User

# # Async DB initializer
# async def init_db():
#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.create_all)
#         logging.info("Database initialized successfully.")

# app/database.py
import logging
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.config import settings

DATABASE_URL = settings.DATABASE_URL

url = make_url(DATABASE_URL)
connect_args = {}
if url.get_backend_name() == "sqlite":
    connect_args["check_same_thread"] = False

# --- Async engine (FastAPI runtime) ---
engine = create_async_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=(settings.ENVIRONMENT != "production"),
)

async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# --- Sync engine (Alembic migrations) ---
SYNC_DATABASE_URL = DATABASE_URL
if "+asyncpg" in DATABASE_URL:
    SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "+psycopg2")

elif "+aiosqlite" in DATABASE_URL:
    SYNC_DATABASE_URL = DATABASE_URL.replace("+aiosqlite", "")

sync_engine = create_engine(
    SYNC_DATABASE_URL,
    connect_args=connect_args,
    echo=(settings.ENVIRONMENT != "production"),
)

SyncSessionLocal = sessionmaker(bind=sync_engine)

# Import models so Alembic detects them
from app.models.user import User  # noqa

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logging.info("Database initialized successfully.")