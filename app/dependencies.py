# from app.database import async_session
# from sqlalchemy.ext.asyncio import AsyncSession

# async def get_db() -> AsyncSession:
#     async with async_session() as session:
#         yield session
from typing import AsyncGenerator
from app.database import async_session
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting async database sessions.
    Properly manages session lifecycle to avoid connection conflicts.
    """
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
