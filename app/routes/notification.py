from app.dependencies import get_db
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.notification_ws import manager
from app.utils.security import get_current_user_ws

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.websocket("/ws/read")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()  # Must accept first

    # Create DB session
    async with get_db() as db:
        try:
            # Extract token from cookies
            token = websocket.cookies.get("access_token")
            if not token:
                await websocket.close(code=1008)
                return

            # Decode token and get user
            user = await get_current_user_ws(websocket, db)
            user_id = user.id

            # Register connection
            await manager.connect(user_id, websocket)

            while True:
                data = await websocket.receive_text()
                print(f"Message from {user_id}: {data}")

                # Example: echo back to the same user
                await manager.send_personal_message(f"You said: {data}", user_id)

        except WebSocketDisconnect:
            manager.disconnect(user_id, websocket)
            print(f"User {user_id} disconnected")
        except Exception as e:
            manager.disconnect(user_id, websocket)
            print(f"Error for user {user_id}: {e}")
            await websocket.close(code=1008)