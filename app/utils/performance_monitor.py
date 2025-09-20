from functools import wraps
import time
import logging
logger = logging.getLogger(__name__)


def performance_monitor(func):
    """Decorator to monitor function performance"""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            execution_time = time.time() - start_time
            if execution_time > 0.1:  # Log only if > 100ms
                logger.info(f"{func.__name__} executed in {execution_time:.3f} seconds")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                f"{func.__name__} failed after {execution_time:.3f} seconds: {e}"
            )
            raise

    return wrapper
