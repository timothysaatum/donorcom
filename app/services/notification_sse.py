"""
SSE Notification Manager

Manages Server-Sent Events (SSE) connections for real-time notifications.
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages SSE connections and notifications"""

    def __init__(self):
        # Store connections: user_id -> list of queues
        self._connections: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def add_sse_connection(self, user_id: str) -> asyncio.Queue:
        """
        Add a new SSE connection for a user.

        Args:
            user_id: User ID to add connection for

        Returns:
            asyncio.Queue: Queue for sending events to this connection
        """
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = []

            # Create a new queue for this connection
            queue = asyncio.Queue(maxsize=100)
            self._connections[user_id].append(queue)

            logger.info(
                f"SSE connection added for user {user_id}. Total connections: {len(self._connections[user_id])}"
            )
            return queue

    async def disconnect_sse(self, user_id: str, queue: asyncio.Queue):
        """
        Remove an SSE connection for a user.

        Args:
            user_id: User ID to remove connection for
            queue: Queue to remove
        """
        async with self._lock:
            if user_id in self._connections:
                try:
                    self._connections[user_id].remove(queue)

                    # Clean up empty user entries
                    if not self._connections[user_id]:
                        del self._connections[user_id]

                    logger.info(f"SSE connection removed for user {user_id}")
                except ValueError:
                    logger.warning(f"Queue not found for user {user_id}")

    def get_user_connection_count(self, user_id: str) -> int:
        """
        Get the number of active connections for a specific user.

        Args:
            user_id: User ID to check connections for

        Returns:
            int: Number of active connections for the user
        """
        return len(self._connections.get(user_id, []))

    async def send_personal_message(self, user_id: str, message: dict) -> bool:
        """
        Send a message to a specific user's connections.

        Args:
            user_id: User ID to send message to
            message: Message dictionary to send

        Returns:
            bool: True if message was sent to at least one connection
        """
        if user_id not in self._connections:
            logger.debug(f"No connections found for user {user_id}")
            return False

        queues = self._connections[user_id].copy()
        sent_count = 0

        for queue in queues:
            try:
                await queue.put(message)
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send message to user {user_id}: {e}")

        logger.debug(
            f"Message sent to {sent_count} connections for user {user_id}"
        )
        return sent_count > 0

    async def broadcast(self, message: dict) -> int:
        """
        Broadcast a message to all connected users.

        Args:
            message: Message dictionary to broadcast

        Returns:
            int: Number of connections message was sent to
        """
        sent_count = 0

        for user_id in list(self._connections.keys()):
            if await self.send_personal_message(user_id, message):
                sent_count += len(self._connections.get(user_id, []))

        logger.info(f"Broadcast message sent to {sent_count} connections")
        return sent_count

    def get_stats(self) -> dict:
        """
        Get connection statistics.

        Returns:
            dict: Statistics about current connections
        """
        total_connections = sum(len(queues) for queues in self._connections.values())
        active_users = len(self._connections)

        return {
            "total_connections": total_connections,
            "active_users": active_users,
            "users": list(self._connections.keys()),
            "connections_per_user": {
                user_id: len(queues)
                for user_id, queues in self._connections.items()
            },
        }


# Global connection manager instance
manager = ConnectionManager()


__all__ = ["ConnectionManager", "manager"]
        total_connections = sum(len(queues) for queues in self.sse_connections.values())
        active_users = len(self.sse_connections)

        return {
            "total_connections": total_connections,
            "active_users": active_users,
            "users": list(self.sse_connections.keys()),
            "connections_per_user": {
                user_id: len(queues)
                for user_id, queues in self.sse_connections.items()
            }
        }

    async def disconnect_user_by_permission_change(self, user_id: str):
        """Force disconnect when permissions are revoked"""
        if user_id in self.active_connections:
            # Send termination event before closing
            termination_event = {
                "type": "connection_terminated",
                "reason": "permissions_revoked",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await self.send_personal_message(termination_event, user_id)
            self.disconnect_sse(user_id, self.active_connections[user_id])


# Create global manager instance
manager = ConnectionManager()
