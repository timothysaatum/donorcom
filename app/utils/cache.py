"""
Enhanced Session and User Caching Implementation

This module provides advanced caching functionality to reduce database load
for frequently accessed session and user data with intelligent cache management,
performance monitoring, and automatic optimization.
"""

from typing import Optional, Dict, Set, List, Any, Tuple
from datetime import datetime, timezone, timedelta
from uuid import UUID
import threading
import time
import asyncio
import hashlib
import json
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, asdict

from app.models.user_model import User, UserSession
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class CacheStats:
    """Cache performance statistics"""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    cache_size: int = 0
    memory_usage_mb: float = 0.0
    avg_access_time_ms: float = 0.0
    hit_rate: float = 0.0
    last_cleanup: datetime = None
    cache_warming_active: bool = False


@dataclass
class UserCacheEntry:
    """Enhanced user cache entry with metadata"""

    user: User
    cached_at: datetime
    expires_at: datetime
    access_count: int = 0
    last_accessed: datetime = None
    permissions_cache: Optional[Set[str]] = None
    roles_cache: Optional[List[str]] = None
    hash_key: Optional[str] = None

    def __post_init__(self):
        if self.last_accessed is None:
            self.last_accessed = self.cached_at


class EnhancedSessionCache:
    """
    Advanced caching system with intelligent cache management,
    performance monitoring, and automatic optimization.

    Features:
    - Multi-level caching (session, user, permissions)
    - Intelligent cache warming
    - Performance monitoring and auto-tuning
    - Memory management with smart eviction
    - Cache invalidation strategies
    - Thread-safe operations with minimal locking
    """

    # Enhanced cache configuration
    DEFAULT_SESSION_TTL = 300  # 5 minutes
    DEFAULT_USER_TTL = 1800  # 30 minutes (longer for user data)
    DEFAULT_PERMISSION_TTL = 3600  # 1 hour for permissions
    MAX_SESSIONS = 50000  # Increased capacity
    MAX_USERS = 25000  # Increased user cache
    MAX_MEMORY_MB = 512  # Memory limit in MB

    # Performance optimization
    CACHE_WARM_INTERVAL = 300  # 5 minutes
    CLEANUP_INTERVAL = 60  # 1 minute
    PERFORMANCE_SAMPLE_SIZE = 1000

    # Cache storage with enhanced structure
    _session_cache: Dict[UUID, dict] = {}
    _user_cache: Dict[UUID, UserCacheEntry] = {}
    _permission_cache: Dict[str, Set[str]] = {}  # user_id -> permissions
    _user_lookup_cache: Dict[str, UUID] = {}  # email -> user_id for fast lookup

    # Access tracking for intelligent management
    _session_access_times: Dict[UUID, datetime] = {}
    _user_access_times: Dict[UUID, datetime] = {}
    _access_frequency: Dict[UUID, int] = defaultdict(int)
    _cache_warming_queue: Set[UUID] = set()

    # Performance monitoring
    _performance_metrics: Dict[str, List[float]] = defaultdict(list)
    _access_patterns: Dict[str, int] = defaultdict(int)

    # Thread safety with reduced locking
    _session_lock = threading.RLock()
    _user_lock = threading.RLock()
    _stats_lock = threading.RLock()

    # Enhanced statistics
    _stats = {
        "session": CacheStats(last_cleanup=datetime.now(timezone.utc)),
        "user": CacheStats(last_cleanup=datetime.now(timezone.utc)),
        "permission": CacheStats(last_cleanup=datetime.now(timezone.utc)),
    }

    # Cache warming and optimization
    _last_optimization = datetime.now(timezone.utc)
    _optimization_interval = timedelta(minutes=15)

    @classmethod
    def cache_session(cls, session: UserSession, ttl: Optional[int] = None) -> None:
        """Enhanced session caching with performance tracking"""
        start_time = time.time()

        if ttl is None:
            ttl = cls.DEFAULT_SESSION_TTL

        with cls._session_lock:
            # Memory management
            if len(cls._session_cache) >= cls.MAX_SESSIONS:
                cls._evict_sessions_intelligent()

            expiry = datetime.now(timezone.utc) + timedelta(seconds=ttl)

            cls._session_cache[session.id] = {
                "session": session,
                "expires": expiry,
                "cached_at": datetime.now(timezone.utc),
                "access_count": 0,
                "size_estimate": cls._estimate_session_size(session),
            }
            cls._session_access_times[session.id] = datetime.now(timezone.utc)

            # Update statistics
            with cls._stats_lock:
                cls._stats["session"].cache_size = len(cls._session_cache)

        # Performance tracking
        processing_time = (time.time() - start_time) * 1000
        cls._record_performance("session_cache", processing_time)

        logger.debug(
            f"Session cached with enhanced tracking",
            extra={
                "event_type": "session_cached_enhanced",
                "session_id": str(session.id),
                "ttl": ttl,
                "processing_time_ms": processing_time,
                "cache_size": len(cls._session_cache),
            },
        )

    @classmethod
    def cache_user(
        cls, user: User, ttl: Optional[int] = None, include_permissions: bool = True
    ) -> None:
        """Enhanced user caching with permissions and roles"""
        start_time = time.time()

        if ttl is None:
            ttl = cls.DEFAULT_USER_TTL

        # Prepare user data with relationships
        permissions_set = None
        roles_list = None

        if include_permissions and hasattr(user, "roles"):
            try:
                permissions_set = set()
                roles_list = []
                for role in user.roles:
                    roles_list.append(role.name)
                    if hasattr(role, "permissions"):
                        for perm in role.permissions:
                            permissions_set.add(perm.name)
            except Exception as e:
                logger.warning(f"Error caching user permissions: {e}")

        # Create cache entry
        cache_entry = UserCacheEntry(
            user=user,
            cached_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
            permissions_cache=permissions_set,
            roles_cache=roles_list,
            hash_key=cls._generate_user_hash(user),
        )

        with cls._user_lock:
            # Memory management
            if len(cls._user_cache) >= cls.MAX_USERS:
                cls._evict_users_intelligent()

            cls._user_cache[user.id] = cache_entry
            cls._user_access_times[user.id] = datetime.now(timezone.utc)

            # Cache email lookup
            if user.email:
                cls._user_lookup_cache[user.email.lower()] = user.id

            # Cache permissions separately for faster access
            if permissions_set:
                cls._permission_cache[str(user.id)] = permissions_set

            # Update statistics
            with cls._stats_lock:
                cls._stats["user"].cache_size = len(cls._user_cache)

        # Performance tracking
        processing_time = (time.time() - start_time) * 1000
        cls._record_performance("user_cache", processing_time)

        logger.debug(
            f"User cached with enhanced data",
            extra={
                "event_type": "user_cached_enhanced",
                "user_id": str(user.id),
                "ttl": ttl,
                "has_permissions": permissions_set is not None,
                "permissions_count": len(permissions_set) if permissions_set else 0,
                "processing_time_ms": processing_time,
                "cache_size": len(cls._user_cache),
            },
        )

    @classmethod
    def get_session(cls, session_id: UUID) -> Optional[UserSession]:
        """Enhanced session retrieval with performance tracking"""
        start_time = time.time()

        with cls._session_lock:
            cache_entry = cls._session_cache.get(session_id)

            if cache_entry is None:
                with cls._stats_lock:
                    cls._stats["session"].misses += 1
                cls._record_performance(
                    "session_get", (time.time() - start_time) * 1000
                )
                return None

            # Check if expired
            if datetime.now(timezone.utc) > cache_entry["expires"]:
                cls._remove_session(session_id)
                with cls._stats_lock:
                    cls._stats["session"].misses += 1
                cls._record_performance(
                    "session_get", (time.time() - start_time) * 1000
                )
                return None

            # Update access tracking
            cache_entry["access_count"] += 1
            cls._session_access_times[session_id] = datetime.now(timezone.utc)
            cls._access_frequency[session_id] += 1

            with cls._stats_lock:
                cls._stats["session"].hits += 1
                cls._update_hit_rate("session")

        processing_time = (time.time() - start_time) * 1000
        cls._record_performance("session_get", processing_time)

        return cache_entry["session"]

    @classmethod
    def get_user(cls, user_id: UUID) -> Optional[User]:
        """Enhanced user retrieval with validation"""
        start_time = time.time()

        with cls._user_lock:
            cache_entry = cls._user_cache.get(user_id)

            if cache_entry is None:
                with cls._stats_lock:
                    cls._stats["user"].misses += 1
                cls._record_performance("user_get", (time.time() - start_time) * 1000)
                return None

            # Check if expired
            if datetime.now(timezone.utc) > cache_entry.expires_at:
                cls._remove_user(user_id)
                with cls._stats_lock:
                    cls._stats["user"].misses += 1
                cls._record_performance("user_get", (time.time() - start_time) * 1000)
                return None

            # Update access tracking
            cache_entry.access_count += 1
            cache_entry.last_accessed = datetime.now(timezone.utc)
            cls._user_access_times[user_id] = datetime.now(timezone.utc)
            cls._access_frequency[user_id] += 1

            with cls._stats_lock:
                cls._stats["user"].hits += 1
                cls._update_hit_rate("user")

        processing_time = (time.time() - start_time) * 1000
        cls._record_performance("user_get", processing_time)

        return cache_entry.user

    @classmethod
    def get_user_by_email(cls, email: str) -> Optional[User]:
        """Fast user lookup by email"""
        user_id = cls._user_lookup_cache.get(email.lower())
        if user_id:
            return cls.get_user(user_id)
        return None

    @classmethod
    def get_user_permissions(cls, user_id: UUID) -> Optional[Set[str]]:
        """Fast permission lookup"""
        start_time = time.time()

        permissions = cls._permission_cache.get(str(user_id))
        if permissions:
            with cls._stats_lock:
                cls._stats["permission"].hits += 1
                cls._update_hit_rate("permission")
        else:
            with cls._stats_lock:
                cls._stats["permission"].misses += 1

        processing_time = (time.time() - start_time) * 1000
        cls._record_performance("permission_get", processing_time)

        return permissions

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
            return EnhancedSessionCache.cleanup_expired()
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


# Backwards compatibility alias
SessionCache = EnhancedSessionCache
