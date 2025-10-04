# import logging
# from sqlalchemy.engine.url import make_url
# from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
# from sqlalchemy import create_engine
# from sqlalchemy.orm import sessionmaker
# from app.db.base import Base

# # --- Async engine (FastAPI runtime) ---
# from app.config import settings

# DATABASE_URL = settings.DATABASE_URL

# url = make_url(DATABASE_URL)
# connect_args = {}
# if url.get_backend_name() == "sqlite":
#     connect_args["check_same_thread"] = False

# # --- Async engine (FastAPI runtime) ---
# engine = create_async_engine(
#     DATABASE_URL,
#     connect_args=connect_args,
#     echo=(settings.ENVIRONMENT != "production"),
# )

# async_session = async_sessionmaker(
#     bind=engine,
#     class_=AsyncSession,
#     expire_on_commit=False,
# )

# # --- Sync engine (Alembic migrations) ---
# SYNC_DATABASE_URL = DATABASE_URL
# if "+asyncpg" in DATABASE_URL:
#     SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "+psycopg2")

# elif "+aiosqlite" in DATABASE_URL:
#     SYNC_DATABASE_URL = DATABASE_URL.replace("+aiosqlite", "")

# sync_engine = create_engine(
#     SYNC_DATABASE_URL,
#     connect_args=connect_args,
#     echo=(settings.ENVIRONMENT != "production"),
# )

# SyncSessionLocal = sessionmaker(bind=sync_engine)

# # Import models so Alembic detects them
# from app.models.user import User # noqa
# from app.models.health_facility import Facility  # noqa
# from app.models.blood_bank import BloodBank  # noqa
# from app.models.inventory import BloodInventory  # noqa
# from app.models.distribution import BloodDistribution  # noqa

# async def init_db():
#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.create_all)
#         logging.info("Database initialized successfully.")
import logging
import os
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

# Check if running on Vercel (serverless)
IS_SERVERLESS = (
    os.getenv("VERCEL") == "1" or os.getenv("AWS_LAMBDA_FUNCTION_NAME") is not None
)

# --- Async engine (FastAPI runtime) ---
# Serverless-optimized configuration
if IS_SERVERLESS:
    engine = create_async_engine(
        DATABASE_URL,
        connect_args={
            **connect_args,
            "server_settings": {
                "application_name": "fastapi_vercel",
                "jit": "off",  # Disable JIT for faster cold starts
            },
            "command_timeout": 10,  # Shorter timeout for serverless
            "timeout": 10,
        },
        pool_size=1,  # Minimal pool for serverless
        max_overflow=0,  # No overflow connections
        pool_pre_ping=True,  # Check connection health before use
        pool_recycle=300,  # Recycle connections after 5 minutes
        echo=(settings.ENVIRONMENT != "production"),
    )
else:
    # Traditional configuration for local development
    engine = create_async_engine(
        DATABASE_URL,
        connect_args=connect_args,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
        pool_pre_ping=True,
        echo=(settings.ENVIRONMENT != "production"),
    )

async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,  # Prevent automatic flushes
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
from app.models.health_facility import Facility  # noqa
from app.models.blood_bank import BloodBank  # noqa
from app.models.inventory import BloodInventory  # noqa
from app.models.distribution import BloodDistribution  # noqa


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logging.info("Database initialized successfully.")


async def close_db():
    """Close database connections gracefully"""
    await engine.dispose()
    logging.info("Database connections closed.")
