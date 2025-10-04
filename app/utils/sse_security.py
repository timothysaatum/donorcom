"""
SSE Security Utilities

Additional security measures for SSE connections with exposed tokens.
"""

from typing import Dict, Optional
from datetime import datetime, timedelta, timezone
import hashlib
from collections import defaultdict


class SSESecurityManager:
    """Manages security for SSE connections"""

    def __init__(self):
        # Track token usage to detect abuse
        self._token_usage: Dict[str, list] = defaultdict(list)
        # Track failed attempts per IP
        self._failed_attempts: Dict[str, list] = defaultdict(list)

    def record_token_use(self, token_hash: str) -> bool:
        """
        Record token usage and check for abuse.
        Returns False if token is being abused (used too frequently).
        """
        current_time = datetime.now(timezone.utc)
        token_id = hashlib.sha256(token_hash.encode()).hexdigest()[:16]

        # Clean old entries (older than 1 hour)
        self._token_usage[token_id] = [
            t
            for t in self._token_usage[token_id]
            if current_time - t < timedelta(hours=1)
        ]

        # Check if token is being reused too frequently (max 5 times per hour)
        if len(self._token_usage[token_id]) >= 5:
            return False

        self._token_usage[token_id].append(current_time)
        return True

    def record_failed_attempt(self, ip_address: str) -> bool:
        """
        Record failed authentication attempt.
        Returns False if IP should be blocked (too many failures).
        """
        current_time = datetime.now(timezone.utc)

        # Clean old entries (older than 15 minutes)
        self._failed_attempts[ip_address] = [
            t
            for t in self._failed_attempts[ip_address]
            if current_time - t < timedelta(minutes=15)
        ]

        # Check if IP has too many failures (max 10 per 15 minutes)
        if len(self._failed_attempts[ip_address]) >= 10:
            return False

        self._failed_attempts[ip_address].append(current_time)
        return True

    def is_ip_blocked(self, ip_address: str) -> bool:
        """Check if IP is currently blocked"""
        current_time = datetime.now(timezone.utc)

        # Clean old entries
        self._failed_attempts[ip_address] = [
            t
            for t in self._failed_attempts[ip_address]
            if current_time - t < timedelta(minutes=15)
        ]

        return len(self._failed_attempts[ip_address]) >= 10


# Global instance
sse_security = SSESecurityManager()
