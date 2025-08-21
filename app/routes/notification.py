from app.models.user import User
from app.utils.security import get_current_user
from fastapi import APIRouter, WebSocket, Depends
from app.services.notification_ws import manager

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str, user: User = Depends(get_current_user)):
    await manager.connect(user_id, websocket)
    try:
        while True:
            # Listen if client sends a ping or ack
            data = await websocket.receive_text()
            print(f"Message from {user_id}: {data}")
    except Exception:
        manager.disconnect(user_id, websocket)
