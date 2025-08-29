from typing import Dict, List
import json
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # Stores all connections per user_id
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()  # Don't forget to accept the connection!
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        print(f"User {user_id} connected. Total connections: {len(self.active_connections[user_id])}")

    def disconnect(self, user_id: str, websocket: WebSocket):
        if user_id in self.active_connections:
            try:
                self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
                print(f"User {user_id} disconnected")
            except ValueError:
                print(f"WebSocket not found for user {user_id}")

    async def send_personal_message(self, user_id: str, message):
        """
        Send a message to a specific user.
        Fixed parameter order: user_id first, message second
        """
        # Ensure user_id is a string
        if isinstance(user_id, dict):
            user_id = str(user_id.get('id', user_id))
        elif hasattr(user_id, 'id'):
            user_id = str(user_id.id)
        else:
            user_id = str(user_id)
        
        connections = self.active_connections.get(user_id, [])
        
        if not connections:
            print(f"No active connections for user {user_id}")
            return
        
        # Convert message to JSON string if it's not already a string
        if isinstance(message, dict):
            message_str = json.dumps(message)
        else:
            message_str = str(message)
        
        # Send to all connections for this user
        disconnected_connections = []
        for connection in connections:
            try:
                await connection.send_text(message_str)
            except Exception as e:
                print(f"Failed to send message to connection: {e}")
                disconnected_connections.append(connection)
        
        # Clean up broken connections
        for broken_connection in disconnected_connections:
            connections.remove(broken_connection)

    async def broadcast(self, message):
        """Send message to all connected users."""
        # Convert message to JSON string if it's not already a string
        if isinstance(message, dict):
            message_str = json.dumps(message)
        else:
            message_str = str(message)
            
        # Send to all users
        for user_id, connections in list(self.active_connections.items()):
            disconnected_connections = []
            for connection in connections:
                try:
                    await connection.send_text(message_str)
                except Exception as e:
                    print(f"Failed to broadcast to user {user_id}: {e}")
                    disconnected_connections.append(connection)
            
            # Clean up broken connections
            for broken_connection in disconnected_connections:
                connections.remove(broken_connection)
            
            # Remove user if no connections left
            if not connections:
                del self.active_connections[user_id]

manager = ConnectionManager()