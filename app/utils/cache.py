"""
Session and User Caching Implementation

This module provides caching functionality to reduce database load
for frequently accessed session and user data.
"""

from typing import Optional, Dict, Set
from datetime import datetime, timezone, timedelta
from uuid import UUID
import threading
import time
from app.models.user import User, UserSession
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class SessionCache:
    """
    In-memory cache for sessions and users to reduce database queries.

    This cache implementation includes:
    - TTL (Time To Live) for automatic expiration
    - Thread-safe operations
    - Memory management with size limits
    - Performance monitoring
    """

    # Cache configuration
    DEFAULT_SESSION_TTL = 300  # 5 minutes
    DEFAULT_USER_TTL = 600  # 10 minutes
    MAX_SESSIONS = 10000  # Maximum number of cached sessions
    MAX_USERS = 5000  # Maximum number of cached users

    # Cache storage
    _session_cache: Dict[UUID, dict] = {}
    _user_cache: Dict[UUID, dict] = {}
    _session_access_times: Dict[UUID, datetime] = {}
    _user_access_times: Dict[UUID, datetime] = {}

    # Thread safety
    _lock = threading.RLock()

    # Statistics
    _stats = {
        "session_hits": 0,
        "session_misses": 0,
        "user_hits": 0,
        "user_misses": 0,
        "evictions": 0,
        "last_cleanup": datetime.now(timezone.utc),
    }

    @classmethod
    def cache_session(cls, session: UserSession, ttl: Optional[int] = None) -> None:
        """Cache a session with TTL"""
        if ttl is None:
            ttl = cls.DEFAULT_SESSION_TTL

        with cls._lock:
            # Check cache size and evict if necessary
            if len(cls._session_cache) >= cls.MAX_SESSIONS:
                cls._evict_oldest_sessions(int(cls.MAX_SESSIONS * 0.1))  # Remove 10%

            expiry = datetime.now(timezone.utc) + timedelta(seconds=ttl)

            cls._session_cache[session.id] = {
                "session": session,
                "expires": expiry,
                "cached_at": datetime.now(timezone.utc),
            }
            cls._session_access_times[session.id] = datetime.now(timezone.utc)

            logger.debug(
                f"Session cached: {session.id}",
                extra={
                    "event_type": "session_cached",
                    "session_id": str(session.id),
                    "ttl": ttl,
                },
            )

    @classmethod
    def get_session(cls, session_id: UUID) -> Optional[UserSession]:
        """Retrieve a session from cache"""
        with cls._lock:
            cache_entry = cls._session_cache.get(session_id)

            if cache_entry is None:
                cls._stats["session_misses"] += 1
                return None

            # Check if expired
            if datetime.now(timezone.utc) > cache_entry["expires"]:
                cls._remove_session(session_id)
                cls._stats["session_misses"] += 1
                return None

            # Update access time
            cls._session_access_times[session_id] = datetime.now(timezone.utc)
            cls._stats["session_hits"] += 1

            return cache_entry["session"]

    @classmethod
    def cache_user(cls, user: User, ttl: Optional[int] = None) -> None:
        """Cache a user with TTL"""
        if ttl is None:
            ttl = cls.DEFAULT_USER_TTL

        with cls._lock:
            # Check cache size and evict if necessary
            if len(cls._user_cache) >= cls.MAX_USERS:
                cls._evict_oldest_users(int(cls.MAX_USERS * 0.1))  # Remove 10%

            expiry = datetime.now(timezone.utc) + timedelta(seconds=ttl)

            cls._user_cache[user.id] = {
                "user": user,
                "expires": expiry,
                "cached_at": datetime.now(timezone.utc),
            }
            cls._user_access_times[user.id] = datetime.now(timezone.utc)

            logger.debug(
                f"User cached: {user.id}",
                extra={
                    "event_type": "user_cached",
                    "user_id": str(user.id),
                    "ttl": ttl,
                },
            )

    @classmethod
    def get_user(cls, user_id: UUID) -> Optional[User]:
        """Retrieve a user from cache"""
        with cls._lock:
            cache_entry = cls._user_cache.get(user_id)

            if cache_entry is None:
                cls._stats["user_misses"] += 1
                return None

            # Check if expired
            if datetime.now(timezone.utc) > cache_entry["expires"]:
                cls._remove_user(user_id)
                cls._stats["user_misses"] += 1
                return None

            # Update access time
            cls._user_access_times[user_id] = datetime.now(timezone.utc)
            cls._stats["user_hits"] += 1

            return cache_entry["user"]

    @classmethod
    def invalidate_session(cls, session_id: UUID) -> None:
        """Remove a session from cache"""
        with cls._lock:
            cls._remove_session(session_id)

    @classmethod
    def invalidate_user(cls, user_id: UUID) -> None:
        """Remove a user from cache"""
        with cls._lock:
            cls._remove_user(user_id)

    @classmethod
    def invalidate_user_sessions(cls, user_id: UUID) -> None:
        """Remove all sessions for a specific user"""
        with cls._lock:
            sessions_to_remove = []

            for session_id, cache_entry in cls._session_cache.items():
                if cache_entry["session"].user_id == user_id:
                    sessions_to_remove.append(session_id)

            for session_id in sessions_to_remove:
                cls._remove_session(session_id)

            logger.debug(
                f"Invalidated {len(sessions_to_remove)} sessions for user {user_id}",
                extra={
                    "event_type": "user_sessions_invalidated",
                    "user_id": str(user_id),
                    "sessions_removed": len(sessions_to_remove),
                },
            )

    @classmethod
    def _remove_session(cls, session_id: UUID) -> None:
        """Internal method to remove session (called with lock held)"""
        cls._session_cache.pop(session_id, None)
        cls._session_access_times.pop(session_id, None)

    @classmethod
    def _remove_user(cls, user_id: UUID) -> None:
        """Internal method to remove user (called with lock held)"""
        cls._user_cache.pop(user_id, None)
        cls._user_access_times.pop(user_id, None)

    @classmethod
    def _evict_oldest_sessions(cls, count: int) -> None:
        """Evict oldest accessed sessions"""
        if not cls._session_access_times:
            return

        # Sort by access time and remove oldest
        sorted_sessions = sorted(cls._session_access_times.items(), key=lambda x: x[1])

        for session_id, _ in sorted_sessions[:count]:
            cls._remove_session(session_id)
            cls._stats["evictions"] += 1

    @classmethod
    def _evict_oldest_users(cls, count: int) -> None:
        """Evict oldest accessed users"""
        if not cls._user_access_times:
            return

        # Sort by access time and remove oldest
        sorted_users = sorted(cls._user_access_times.items(), key=lambda x: x[1])

        for user_id, _ in sorted_users[:count]:
            cls._remove_user(user_id)
            cls._stats["evictions"] += 1

    @classmethod
    def cleanup_expired(cls) -> dict:
        """Remove all expired entries from cache"""
        with cls._lock:
            now = datetime.now(timezone.utc)

            # Clean expired sessions
            expired_sessions = []
            for session_id, cache_entry in cls._session_cache.items():
                if now > cache_entry["expires"]:
                    expired_sessions.append(session_id)

            for session_id in expired_sessions:
                cls._remove_session(session_id)

            # Clean expired users
            expired_users = []
            for user_id, cache_entry in cls._user_cache.items():
                if now > cache_entry["expires"]:
                    expired_users.append(user_id)

            for user_id in expired_users:
                cls._remove_user(user_id)

            cls._stats["last_cleanup"] = now

            cleanup_stats = {
                "expired_sessions_removed": len(expired_sessions),
                "expired_users_removed": len(expired_users),
                "timestamp": now.isoformat(),
            }

            if expired_sessions or expired_users:
                logger.info(
                    "Cache cleanup completed",
                    extra={"event_type": "cache_cleanup", **cleanup_stats},
                )

            return cleanup_stats

    @classmethod
    def get_stats(cls) -> dict:
        """Get cache statistics"""
        with cls._lock:
            total_session_requests = (
                cls._stats["session_hits"] + cls._stats["session_misses"]
            )
            total_user_requests = cls._stats["user_hits"] + cls._stats["user_misses"]

            session_hit_rate = (
                cls._stats["session_hits"] / total_session_requests * 100
                if total_session_requests > 0
                else 0
            )

            user_hit_rate = (
                cls._stats["user_hits"] / total_user_requests * 100
                if total_user_requests > 0
                else 0
            )

            return {
                "session_cache": {
                    "size": len(cls._session_cache),
                    "max_size": cls.MAX_SESSIONS,
                    "hits": cls._stats["session_hits"],
                    "misses": cls._stats["session_misses"],
                    "hit_rate": f"{session_hit_rate:.2f}%",
                },
                "user_cache": {
                    "size": len(cls._user_cache),
                    "max_size": cls.MAX_USERS,
                    "hits": cls._stats["user_hits"],
                    "misses": cls._stats["user_misses"],
                    "hit_rate": f"{user_hit_rate:.2f}%",
                },
                "general": {
                    "evictions": cls._stats["evictions"],
                    "last_cleanup": cls._stats["last_cleanup"].isoformat(),
                },
            }

    @classmethod
    def clear_all(cls) -> None:
        """Clear all cached data (use with caution)"""
        with cls._lock:
            cls._session_cache.clear()
            cls._user_cache.clear()
            cls._session_access_times.clear()
            cls._user_access_times.clear()

            # Reset stats but keep cleanup time
            last_cleanup = cls._stats["last_cleanup"]
            cls._stats.clear()
            cls._stats.update(
                {
                    "session_hits": 0,
                    "session_misses": 0,
                    "user_hits": 0,
                    "user_misses": 0,
                    "evictions": 0,
                    "last_cleanup": last_cleanup,
                }
            )

            logger.info("All cache data cleared", extra={"event_type": "cache_cleared"})


class CacheManager:
    """Manager for periodic cache maintenance"""

    def __init__(self):
        self._last_cleanup = datetime.now(timezone.utc)
        self._cleanup_interval = 300  # 5 minutes

    def should_cleanup(self) -> bool:
        """Check if cleanup is needed"""
        return (
            datetime.now(timezone.utc) - self._last_cleanup
        ).total_seconds() > self._cleanup_interval

    def perform_cleanup(self) -> dict:
        """Perform cache cleanup if needed"""
        if self.should_cleanup():
            self._last_cleanup = datetime.now(timezone.utc)
            return SessionCache.cleanup_expired()
        return {"message": "cleanup_not_needed"}


# Global cache manager instance
cache_manager = CacheManager()


# Optional: Background cleanup task (if using with task scheduler)
async def periodic_cache_cleanup():
    """Periodic cleanup task for background execution"""
    try:
        if cache_manager.should_cleanup():
            stats = cache_manager.perform_cleanup()
            logger.debug(
                "Periodic cache cleanup completed",
                extra={"event_type": "periodic_cleanup", **stats},
            )
    except Exception as e:
        logger.error(
            "Periodic cache cleanup failed",
            extra={"event_type": "periodic_cleanup_failed", "error": str(e)},
            exc_info=True,
        )
