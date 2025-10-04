# from app.database import async_session
# from sqlalchemy.ext.asyncio import AsyncSession

# async def get_db() -> AsyncSession:
#     async with async_session() as session:
#         yield session
import logging
from app.database import async_session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError, DBAPIError
import asyncio


async def get_db() -> AsyncSession:
    """
    Dependency for getting async database sessions.
    Includes retry logic for transient connection issues.
    """
    max_retries = 3
    retry_delay = 1  # seconds

    for attempt in range(max_retries):
        try:
            async with async_session() as session:
                # Test the connection
                await session.execute("SELECT 1")
                yield session
                await session.commit()
                break
        except (OperationalError, DBAPIError) as e:
            logging.error(
                f"Database connection error (attempt {attempt + 1}/{max_retries}): {e}"
            )

            if attempt == max_retries - 1:
                # Last attempt failed
                raise

            # Wait before retrying
            await asyncio.sleep(retry_delay)
        except Exception as e:
            # For non-connection errors, don't retry
            logging.error(f"Unexpected database error: {e}")
            raise
        finally:
            # Ensure session is closed even if there's an error
            try:
                await session.close()
            except:
                pass
