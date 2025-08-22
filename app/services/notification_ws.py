# from typing import Dict, List
# from fastapi import WebSocket

# class ConnectionManager:
#     def __init__(self):
#         self.active_connections: Dict[str, List[WebSocket]] = {}

#     async def connect(self, user_id: str, websocket: WebSocket):
#         await websocket.accept()
#         if user_id not in self.active_connections:
#             self.active_connections[user_id] = []
#         self.active_connections[user_id].append(websocket)

#     def disconnect(self, user_id: str, websocket: WebSocket):
#         if user_id in self.active_connections:
#             self.active_connections[user_id].remove(websocket)
#             if not self.active_connections[user_id]:
#                 del self.active_connections[user_id]

#     async def send_personal_message(self, user_id: str, message: dict):
#         if user_id in self.active_connections:
#             for connection in self.active_connections[user_id]:
#                 await connection.send_json(message)

#     async def broadcast(self, message: dict):
#         for connections in self.active_connections.values():
#             for connection in connections:
#                 await connection.send_json(message)

# manager = ConnectionManager()
from typing import Dict, List
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # Stores all connections per user_id
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, message: str, user_id: str):
        # Send to all sockets of a single user
        connections = self.active_connections.get(user_id, [])
        for connection in connections:
            await connection.send_text(message)

    async def broadcast(self, message: str):
        # Send to all users
        for connections in self.active_connections.values():
            for connection in connections:
                await connection.send_text(message)

manager = ConnectionManager()
