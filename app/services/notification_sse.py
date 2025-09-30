from typing import Dict, List
import asyncio
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """SSE Connection Manager for real-time notifications"""

    def __init__(self):
        # user_id -> list of asyncio.Queue (for multiple tabs/devices)
        self.sse_connections: Dict[str, List[asyncio.Queue]] = {}

    def add_sse_connection(self, user_id: str) -> asyncio.Queue:
        """Add a new SSE connection (queue) for a user."""
        queue = asyncio.Queue(maxsize=100)  # Prevent memory issues
        if user_id not in self.sse_connections:
            self.sse_connections[user_id] = []
        self.sse_connections[user_id].append(queue)

        logger.info(
            f"SSE connection added for user {user_id}. "
            f"Total connections for user: {len(self.sse_connections[user_id])}"
        )
        return queue

    def disconnect_sse(self, user_id: str, queue: asyncio.Queue):
        """Remove an SSE connection (queue) for a user."""
        if user_id in self.sse_connections:
            try:
                self.sse_connections[user_id].remove(queue)
                if not self.sse_connections[user_id]:
                    del self.sse_connections[user_id]
                logger.info(f"SSE connection removed for user {user_id}")
            except ValueError:
                logger.warning(f"SSE queue not found for user {user_id}")

    async def send_personal_message(self, user_id: str, message: dict) -> bool:
        """
        Send a message to a specific user via SSE.
        Returns True if message was queued, False if user not connected.
        """
        user_id = str(user_id)
        queues = self.sse_connections.get(user_id, [])

        if not queues:
            logger.debug(f"No active SSE connections for user {user_id}")
            return False

        # Send to all connections for this user (multiple tabs/devices)
        sent_count = 0
        dead_queues = []

        for queue in queues[:]:  # Copy list to avoid modification during iteration
            try:
                # Non-blocking put with timeout
                try:
                    queue.put_nowait(message)
                    sent_count += 1
                except asyncio.QueueFull:
                    logger.warning(
                        f"Queue full for user {user_id}, dropping oldest message"
                    )
                    # Drop oldest message and add new one
                    try:
                        queue.get_nowait()
                        queue.put_nowait(message)
                        sent_count += 1
                    except:
                        dead_queues.append(queue)
            except Exception as e:
                logger.error(f"Failed to queue message for user {user_id}: {e}")
                dead_queues.append(queue)

        # Clean up dead queues
        for dead_queue in dead_queues:
            self.disconnect_sse(user_id, dead_queue)

        if sent_count > 0:
            logger.debug(
                f"Message queued for user {user_id} "
                f"({sent_count}/{len(queues)} connections)"
            )

        return sent_count > 0

    async def broadcast(self, message: dict) -> int:
        """
        Send message to all connected users via SSE.
        Returns the number of successful deliveries.
        """
        total_sent = 0
        dead_connections = []

        for user_id, queues in list(self.sse_connections.items()):
            for queue in queues[:]:
                try:
                    try:
                        queue.put_nowait(message)
                        total_sent += 1
                    except asyncio.QueueFull:
                        # Try to make room
                        try:
                            queue.get_nowait()
                            queue.put_nowait(message)
                            total_sent += 1
                        except:
                            dead_connections.append((user_id, queue))
                except Exception as e:
                    logger.error(f"Failed to broadcast to user {user_id}: {e}")
                    dead_connections.append((user_id, queue))

        # Clean up dead connections
        for user_id, queue in dead_connections:
            self.disconnect_sse(user_id, queue)

        logger.info(f"Broadcast sent to {total_sent} connections")
        return total_sent

    def get_connected_users(self) -> List[str]:
        """Get list of currently connected user IDs."""
        return list(self.sse_connections.keys())

    def get_connection_count(self, user_id: str = None) -> int:
        """
        Get number of SSE connections.
        If user_id provided, returns connections for that user.
        Otherwise, returns total connections across all users.
        """
        if user_id:
            return len(self.sse_connections.get(str(user_id), []))
        return sum(len(queues) for queues in self.sse_connections.values())

    def get_stats(self) -> dict:
        """Get connection statistics."""
        return {
            "total_users": len(self.sse_connections),
            "total_connections": self.get_connection_count(),
            "users": {
                user_id: len(queues) for user_id, queues in self.sse_connections.items()
            },
        }


# Create global manager instance
manager = ConnectionManager()
