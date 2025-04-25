from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.db.base import Base
from app.config import settings

# Convert sync SQLite URL to async-compatible one
SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

# Create async engine
engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=True,
)

# Create session factory for async sessions
async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Import models to register with Base
from app.models.user import User

# Async DB initializer
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
