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
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, StaticPool
from app.db.base import Base
from app.config import settings

logger = logging.getLogger(__name__)

DATABASE_URL = settings.DATABASE_URL

url = make_url(DATABASE_URL)
connect_args = {}

# Check if running on Vercel (serverless)
IS_SERVERLESS = (
    os.getenv("VERCEL") == "1" or os.getenv("AWS_LAMBDA_FUNCTION_NAME") is not None
)

logger.info(f"Database backend: {url.get_backend_name()}")
logger.info(f"Serverless mode: {IS_SERVERLESS}")

# --- Async engine (FastAPI runtime) ---
if IS_SERVERLESS:
    logger.info("Configuring database for serverless environment")

    # PostgreSQL-specific settings for asyncpg
    if url.get_backend_name() == "postgresql":
        connect_args = {
            "server_settings": {
                "application_name": "fastapi_vercel",
                "jit": "off",
            },
            "timeout": 30,
            "command_timeout": 30,
            # CRITICAL: Disable all statement caching to prevent conflicts
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            # Disable automatic BEGIN statements
            "server_settings": {
                "application_name": "fastapi_vercel",
                "jit": "off",
                "idle_in_transaction_session_timeout": "30000",
            },
        }
    elif url.get_backend_name() == "sqlite":
        connect_args = {"check_same_thread": False}

    # Use NullPool for serverless - no connection reuse
    engine = create_async_engine(
        DATABASE_URL,
        poolclass=NullPool,
        connect_args=connect_args,
        echo=False,  # Disable echo in production
        isolation_level="AUTOCOMMIT",  # Prevent transaction conflicts
    )

    logger.info("Using NullPool for serverless environment")

else:
    # Traditional configuration for local development
    logger.info("Configuring database for local/traditional environment")

    if url.get_backend_name() == "sqlite":
        connect_args = {"check_same_thread": False}

    engine = create_async_engine(
        DATABASE_URL,
        connect_args=connect_args,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
        pool_pre_ping=True,
        echo=(settings.ENVIRONMENT != "production"),
    )

    logger.info("Using traditional connection pooling")

# Create session factory with proper settings
async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# --- Sync engine (Alembic migrations) ---
SYNC_DATABASE_URL = DATABASE_URL
if "+asyncpg" in DATABASE_URL:
    SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "+psycopg2")
elif "+aiosqlite" in DATABASE_URL:
    SYNC_DATABASE_URL = DATABASE_URL.replace("+aiosqlite", "")

sync_connect_args = {}
if url.get_backend_name() == "sqlite":
    sync_connect_args = {"check_same_thread": False}

sync_engine = create_engine(
    SYNC_DATABASE_URL,
    connect_args=sync_connect_args,
    echo=(settings.ENVIRONMENT != "production"),
)

SyncSessionLocal = sessionmaker(bind=sync_engine)

# Import models so Alembic detects them
from app.models.user_model import User  # noqa
from app.models.health_facility_model import Facility  # noqa
from app.models.blood_bank_model import BloodBank  # noqa
from app.models.inventory_model import BloodInventory  # noqa
from app.models.distribution_model import BloodDistribution  # noqa


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized successfully.")


async def close_db():
    """Close database connections gracefully"""
    try:
        await engine.dispose()
        logger.info("Database connections closed.")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}")
