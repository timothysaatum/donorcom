# from app.database import async_session
# from sqlalchemy.ext.asyncio import AsyncSession

# async def get_db() -> AsyncSession:
#     async with async_session() as session:
#         yield session
import logging
from typing import AsyncGenerator
from app.database import async_session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException

logger = logging.getLogger(__name__)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting async database sessions.
    Properly manages session lifecycle to avoid connection conflicts.
    """
    session = None
    try:
        # Create a new session
        session = async_session()
        logger.debug("Database session created")

        yield session

        # Commit any pending transactions
        if session.in_transaction():
            await session.commit()
            logger.debug("Database transaction committed")

    except HTTPException:
        # Don't catch HTTPException - let FastAPI handle it
        # But still rollback if there's an active transaction
        if session and session.in_transaction():
            await session.rollback()
            logger.debug("Database transaction rolled back due to HTTPException")
        raise

    except SQLAlchemyError as e:
        logger.error(f"Database error in get_db: {type(e).__name__}: {e}")
        if session and session.in_transaction():
            await session.rollback()
            logger.debug("Database transaction rolled back")
        raise

    except Exception as e:
        logger.error(f"Unexpected error in get_db: {type(e).__name__}: {e}")
        if session and session.in_transaction():
            await session.rollback()
        raise

    finally:
        if session:
            await session.close()
            logger.debug("Database session closed")
