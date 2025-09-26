import datetime
from time import timezone
from app.dependencies import get_db
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.notification_ws import manager
from app.utils.security import get_current_user_ws
from app.utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/notifications", tags=["Notifications"])


# @router.websocket("/ws/read")
# async def websocket_endpoint(websocket: WebSocket):
#     """WebSocket endpoint for real-time notifications"""
#     user_id = None

#     try:
#         # Accept the connection first
#         await websocket.accept()

#         # Get database session using the dependency
#         db_gen = get_db()
#         db = await db_gen.__anext__()

#         try:
#             # Authenticate user
#             user = await get_current_user_ws(websocket, db)
#             user_id = str(user.id)

#             # Register connection with the manager
#             await manager.connect(user_id, websocket)

#             logger.info(f"WebSocket connection established for user {user_id}")

#             # Keep connection alive and handle messages
#             while True:
#                 try:
#                     # Receive message from client
#                     data = await websocket.receive_text()
#                     logger.debug(f"Message from {user_id}: {data}")

#                     # Echo back to the same user (you can modify this logic)
#                     await manager.send_personal_message(user_id, f"You said: {data}")

#                 except WebSocketDisconnect:
#                     logger.info(f"User {user_id} disconnected normally")
#                     break
#                 except Exception as e:
#                     logger.error(f"Error handling message from user {user_id}: {e}")
#                     break

#         finally:
#             # Clean up database session
#             await db_gen.aclose()

#     except WebSocketDisconnect:
#         logger.info(f"WebSocket disconnected during setup")
#     except Exception as e:
#         logger.error(f"WebSocket error: {e}")
#         try:
#             await websocket.close(code=1011)  # Internal server error
#         except:
#             pass
#     finally:
#         # Ensure user is disconnected from manager
#         if user_id:
#             manager.disconnect(user_id, websocket)


# # Alternative approach using dependency injection (cleaner)
async def get_websocket_db():
    """Get database session for WebSocket connections"""
    db_gen = get_db()
    db = await db_gen.__anext__()
    try:
        yield db
    finally:
        await db_gen.aclose()


@router.websocket("/ws/read")
async def websocket_endpoint_alt(websocket: WebSocket):
    """Alternative WebSocket endpoint with cleaner DB handling"""
    user_id = None

    try:
        await websocket.accept()

        # Use the helper function to get DB session
        async for db in get_websocket_db():
            try:
                # Authenticate user
                user = await get_current_user_ws(websocket, db)
                user_id = str(user.id)

                # Register connection
                await manager.connect(user_id, websocket)
                logger.info(f"WebSocket connection established for user {user_id}")

                # Handle messages
                while True:
                    try:
                        data = await websocket.receive_text()
                        logger.debug(f"Message from {user_id}: {data}")

                        # Process message (customize this logic as needed)
                        await manager.send_personal_message(
                            user_id,
                            {
                                "type": "echo",
                                "message": data,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        )

                    except WebSocketDisconnect:
                        logger.info(f"User {user_id} disconnected")
                        break
                    except Exception as e:
                        logger.error(f"Error handling message: {e}")
                        break

            except Exception as e:
                logger.error(f"Authentication or connection error: {e}")
                try:
                    await websocket.close(code=1008)  # Policy violation
                except:
                    pass
                break

    except Exception as e:
        logger.error(f"WebSocket setup error: {e}")
    finally:
        if user_id:
            manager.disconnect(user_id, websocket)
