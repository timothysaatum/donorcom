import hashlib
import json
import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional, Callable, Dict, Union
from functools import wraps
import logging

logger = logging.getLogger(__name__)


class CacheManager:
    """Generic cache manager with TTL support."""

    def __init__(self, default_ttl: int = 300, max_size: int = 1000):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl
        self.max_size = max_size

    def _generate_key(self, *args, **kwargs) -> str:
        """Generate a consistent cache key from arguments."""
        # Convert args and kwargs to a consistent string representation
        key_data = {
            "args": [str(arg) for arg in args],
            "kwargs": {k: str(v) for k, v in sorted(kwargs.items())},
        }
        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_string.encode()).hexdigest()

    def _is_expired(self, entry: Dict[str, Any]) -> bool:
        """Check if cache entry has expired."""
        return datetime.now() > entry["expires_at"]

    def _cleanup_expired(self):
        """Remove expired entries."""
        expired_keys = [
            key for key, entry in self._cache.items() if self._is_expired(entry)
        ]
        for key in expired_keys:
            del self._cache[key]

    def _cleanup_lru(self):
        """Remove least recently used entries if cache is full."""
        if len(self._cache) >= self.max_size:
            # Sort by last accessed time and remove oldest 10%
            sorted_items = sorted(
                self._cache.items(), key=lambda x: x[1]["last_accessed"]
            )
            items_to_remove = len(sorted_items) // 10 or 1
            for key, _ in sorted_items[:items_to_remove]:
                del self._cache[key]

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if key in self._cache:
            entry = self._cache[key]
            if self._is_expired(entry):
                del self._cache[key]
                return None

            # Update last accessed time
            entry["last_accessed"] = datetime.now()
            return entry["value"]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with TTL."""
        ttl = ttl or self.default_ttl

        self._cleanup_expired()
        self._cleanup_lru()

        self._cache[key] = {
            "value": value,
            "expires_at": datetime.now() + timedelta(seconds=ttl),
            "last_accessed": datetime.now(),
            "created_at": datetime.now(),
        }

    def delete(self, key: str) -> bool:
        """Delete specific key from cache."""
        return self._cache.pop(key, None) is not None

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "total_entries": len(self._cache),
            "max_size": self.max_size,
            "default_ttl": self.default_ttl,
            "expired_entries": len(
                [k for k, v in self._cache.items() if self._is_expired(v)]
            ),
        }


# Global cache instance
cache = CacheManager()


def cached(ttl: Optional[int] = None, key_prefix: str = ""):
    """
    Decorator to cache function results.

    Args:
        ttl: Time to live in seconds (uses default if None)
        key_prefix: Prefix for cache keys
    """

    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Generate cache key
            base_key = cache._generate_key(*args, **kwargs)
            cache_key = f"{key_prefix}:{base_key}" if key_prefix else base_key

            # Try to get from cache
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache hit for function {func.__name__}")
                return cached_result

            # Execute function
            logger.debug(f"Cache miss for function {func.__name__}")
            result = await func(*args, **kwargs)

            # Cache result
            cache.set(cache_key, result, ttl)
            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Generate cache key
            base_key = cache._generate_key(*args, **kwargs)
            cache_key = f"{key_prefix}:{base_key}" if key_prefix else base_key

            # Try to get from cache
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache hit for function {func.__name__}")
                return cached_result

            # Execute function
            logger.debug(f"Cache miss for function {func.__name__}")
            result = func(*args, **kwargs)

            # Cache result
            cache.set(cache_key, result, ttl)
            return result

        # Return appropriate wrapper based on function type
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


def cache_key(*args, **kwargs) -> str:
    """Generate a cache key from arguments (utility function)."""
    return cache._generate_key(*args, **kwargs)


def manual_cache_get(key: str) -> Optional[Any]:
    """Manually get value from cache."""
    return cache.get(key)


def manual_cache_set(key: str, value: Any, ttl: Optional[int] = None) -> None:
    """Manually set value in cache."""
    cache.set(key, value, ttl)


def cache_delete(key: str) -> bool:
    """Delete specific cache entry."""
    return cache.delete(key)


def cache_clear() -> None:
    """Clear all cache."""
    cache.clear()


def cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    return cache.get_stats()


# Context manager for temporary cache settings
class temp_cache_config:
    """Temporarily change cache configuration."""

    def __init__(self, ttl: Optional[int] = None, max_size: Optional[int] = None):
        self.new_ttl = ttl
        self.new_max_size = max_size
        self.old_ttl = None
        self.old_max_size = None

    def __enter__(self):
        self.old_ttl = cache.default_ttl
        self.old_max_size = cache.max_size

        if self.new_ttl is not None:
            cache.default_ttl = self.new_ttl
        if self.new_max_size is not None:
            cache.max_size = self.new_max_size

        return cache

    def __exit__(self, exc_type, exc_val, exc_tb):
        cache.default_ttl = self.old_ttl
        cache.max_size = self.old_max_size
