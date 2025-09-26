import json
from datetime import datetime, timezone
from app.dependencies import get_db
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.notification_ws import manager
from app.utils.security import get_current_user_ws
from app.utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.websocket("/ws/read")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time notifications"""
    user_id = None
    db = None

    try:
        # Get database session first (before accepting websocket)
        db_gen = get_db()
        db = await db_gen.__anext__()

        try:
            # Authenticate user (this will accept the websocket internally)
            user = await get_current_user_ws(websocket, db)
            user_id = str(user.id)

            # Register connection (don't accept again since auth already did it)
            manager.add_connection(user_id, websocket)
            logger.info(f"WebSocket connection established for user {user_id}")

            # Send welcome message
            await manager.send_personal_message(
                user_id,
                {
                    "type": "connection_established",
                    "message": "Successfully connected to notifications",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user_id": user_id,
                },
            )

            # Keep connection alive and handle messages
            while True:
                try:
                    data = await websocket.receive_text()
                    logger.debug(f"Message from {user_id}: {data}")

                    # Parse message
                    try:
                        message = (
                            json.loads(data)
                            if data.startswith("{")
                            else {"content": data}
                        )
                    except json.JSONDecodeError:
                        message = {"content": data}

                    # Handle different message types
                    await handle_websocket_message(user_id, message)

                except WebSocketDisconnect:
                    logger.info(f"User {user_id} disconnected normally")
                    break
                except Exception as e:
                    logger.error(f"Error handling message from user {user_id}: {e}")
                    await manager.send_personal_message(
                        user_id,
                        {
                            "type": "error",
                            "message": "Error processing your message",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )

        finally:
            # Clean up database session
            if db_gen:
                await db_gen.aclose()

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during setup")
    except Exception as e:
        logger.error(f"WebSocket setup error: {e}")
        try:
            if websocket.client_state != websocket.client_state.DISCONNECTED:
                await websocket.close(code=1011)  # Internal server error
        except:
            pass
    finally:
        # Ensure cleanup
        if user_id:
            manager.disconnect(user_id, websocket)


async def handle_websocket_message(user_id: str, message: dict):
    """Handle different types of WebSocket messages"""
    message_type = message.get("type", "unknown")

    try:
        if message_type == "ping":
            await manager.send_personal_message(
                user_id,
                {"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()},
            )
        elif message_type == "get_notifications":
            # In a real implementation, fetch from database
            await manager.send_personal_message(
                user_id,
                {
                    "type": "notifications",
                    "data": [],  # Would be actual notifications
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        elif message_type == "mark_read":
            notification_id = message.get("notification_id")
            # In a real implementation, mark as read in database
            await manager.send_personal_message(
                user_id,
                {
                    "type": "marked_read",
                    "notification_id": notification_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        else:
            # Echo back unknown messages
            await manager.send_personal_message(
                user_id,
                {
                    "type": "echo",
                    "original_message": message,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
    except Exception as e:
        logger.error(
            f"Error handling message type {message_type} for user {user_id}: {e}"
        )
