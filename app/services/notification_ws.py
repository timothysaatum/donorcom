from typing import Dict, List
import json
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # Stores all connections per user_id
        self.active_connections: Dict[str, List[WebSocket]] = {}

    def add_connection(self, user_id: str, websocket: WebSocket):
        """Add connection without accepting (since it's already accepted by auth)"""
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        print(
            f"User {user_id} connected. Total connections: {len(self.active_connections[user_id])}"
        )

    async def connect(self, user_id: str, websocket: WebSocket):
        """Legacy method - only use if websocket not yet accepted"""
        await websocket.accept()
        self.add_connection(user_id, websocket)

    def disconnect(self, user_id: str, websocket: WebSocket):
        """Remove connection for a user"""
        if user_id in self.active_connections:
            try:
                self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
                print(f"User {user_id} disconnected")
            except ValueError:
                print(f"WebSocket not found for user {user_id}")

    async def send_personal_message(self, user_id: str, message):
        """Send a message to a specific user"""
        # Ensure user_id is a string
        user_id = str(user_id)

        connections = self.active_connections.get(user_id, [])

        if not connections:
            print(f"No active connections for user {user_id}")
            return False

        # Convert message to JSON string if it's not already a string
        if isinstance(message, dict):
            message_str = json.dumps(message)
        else:
            message_str = str(message)

        # Send to all connections for this user
        disconnected_connections = []
        successful_sends = 0

        for connection in connections[
            :
        ]:  # Create copy to safely modify during iteration
            try:
                await connection.send_text(message_str)
                successful_sends += 1
            except Exception as e:
                print(f"Failed to send message to connection: {e}")
                disconnected_connections.append(connection)

        # Clean up broken connections
        for broken_connection in disconnected_connections:
            try:
                connections.remove(broken_connection)
            except ValueError:
                pass  # Already removed

        # Remove user entry if no connections left
        if not connections and user_id in self.active_connections:
            del self.active_connections[user_id]

        return successful_sends > 0

    async def broadcast(self, message):
        """Send message to all connected users"""
        if isinstance(message, dict):
            message_str = json.dumps(message)
        else:
            message_str = str(message)

        total_sent = 0
        users_to_remove = []

        for user_id, connections in list(self.active_connections.items()):
            disconnected_connections = []

            for connection in connections[:]:  # Create copy for safe iteration
                try:
                    await connection.send_text(message_str)
                    total_sent += 1
                except Exception as e:
                    print(f"Failed to broadcast to user {user_id}: {e}")
                    disconnected_connections.append(connection)

            # Clean up broken connections
            for broken_connection in disconnected_connections:
                try:
                    connections.remove(broken_connection)
                except ValueError:
                    pass

            # Mark user for removal if no connections left
            if not connections:
                users_to_remove.append(user_id)

        # Remove users with no connections
        for user_id in users_to_remove:
            if user_id in self.active_connections:
                del self.active_connections[user_id]

        return total_sent

    def get_connected_users(self) -> List[str]:
        """Get list of currently connected user IDs"""
        return list(self.active_connections.keys())

    def get_connection_count(self, user_id: str) -> int:
        """Get number of connections for a specific user"""
        return len(self.active_connections.get(str(user_id), []))


# Create global manager instance
manager = ConnectionManager()