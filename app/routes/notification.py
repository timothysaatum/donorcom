import json
from datetime import datetime, timezone
from app.dependencies import get_db
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse
from app.services.notification_sse import manager
from app.utils.permission_checker import require_permission
from app.utils.logging_config import get_logger
import asyncio

logger = get_logger(__name__)
router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/sse/stream")
async def sse_notifications(
    request: Request,
    db=Depends(get_db),
    current_user=Depends(
        require_permission(
            "facility.manage",
            "laboratory.manage",
            "blood.inventory.manage",
            validate_session=True,
        )
    ),
):
    """
    SSE endpoint for real-time notifications streaming.
    Maintains a persistent connection to push server events to the client.
    """
    user_id = str(current_user.id)
    event_queue = manager.add_sse_connection(user_id)

    logger.info(
        f"SSE connection established for user {user_id}",
        extra={
            "event_type": "sse_connection_established",
            "user_id": user_id,
            "user_email": current_user.email,
        },
    )

    async def event_stream():
        """Generator function that yields SSE-formatted events"""
        try:
            # Send initial connection success event
            connection_event = {
                "type": "connection_established",
                "message": "Successfully connected to notification stream",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_id": user_id,
            }
            yield f"data: {json.dumps(connection_event)}\n\n"

            # Send heartbeat every 30 seconds to keep connection alive
            heartbeat_task = asyncio.create_task(send_heartbeat())

            try:
                while True:
                    # Check if client disconnected
                    if await request.is_disconnected():
                        logger.info(
                            f"SSE client {user_id} disconnected",
                            extra={
                                "event_type": "sse_client_disconnected",
                                "user_id": user_id,
                            },
                        )
                        break

                    try:
                        # Wait for event with timeout (for heartbeat)
                        event = await asyncio.wait_for(event_queue.get(), timeout=30.0)

                        # Format and send the event
                        yield f"data: {json.dumps(event)}\n\n"

                        logger.debug(
                            f"SSE event sent to user {user_id}",
                            extra={
                                "event_type": "sse_event_sent",
                                "user_id": user_id,
                                "notification_type": event.get("type"),
                            },
                        )

                    except asyncio.TimeoutError:
                        # Send heartbeat (keep-alive)
                        heartbeat = {
                            "type": "heartbeat",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        yield f": heartbeat\n\n"

                    except Exception as e:
                        logger.error(
                            f"SSE error for user {user_id}: {e}",
                            extra={
                                "event_type": "sse_stream_error",
                                "user_id": user_id,
                                "error": str(e),
                            },
                            exc_info=True,
                        )
                        break

            finally:
                heartbeat_task.cancel()

        except Exception as e:
            logger.error(
                f"SSE stream initialization error for user {user_id}: {e}",
                extra={
                    "event_type": "sse_initialization_error",
                    "user_id": user_id,
                    "error": str(e),
                },
                exc_info=True,
            )
        finally:
            # Clean up connection
            manager.disconnect_sse(user_id, event_queue)
            logger.info(
                f"SSE connection closed for user {user_id}",
                extra={"event_type": "sse_connection_closed", "user_id": user_id},
            )

    async def send_heartbeat():
        """Background task to send periodic heartbeats"""
        while True:
            await asyncio.sleep(30)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/sse/stats")
async def get_sse_stats(
    current_user=Depends(
        require_permission(
            "facility.manage",
            "laboratory.manage",
            validate_session=True,
        )
    ),
):
    """
    Get SSE connection statistics.
    Useful for monitoring and debugging.
    """
    stats = manager.get_stats()

    return {
        "success": True,
        "stats": stats,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/test/send")
async def send_test_notification(
    message: str,
    db=Depends(get_db),
    current_user=Depends(
        require_permission(
            "facility.manage",
            validate_session=True,
        )
    ),
):
    """
    Send a test notification to the current user.
    Useful for testing SSE connection.
    """
    user_id = str(current_user.id)

    notification = {
        "type": "test_notification",
        "title": "Test Notification",
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "priority": "normal",
    }

    success = await manager.send_personal_message(user_id, notification)

    return {
        "success": success,
        "message": "Notification sent" if success else "User not connected",
        "user_id": user_id,
    }


@router.post("/broadcast")
async def broadcast_notification(
    title: str,
    message: str,
    notification_type: str = "system",
    priority: str = "normal",
    db=Depends(get_db),
    current_user=Depends(
        require_permission(
            "facility.manage",
            validate_session=True,
        )
    ),
):
    """
    Broadcast a notification to all connected users.
    Requires appropriate permissions.
    """
    notification = {
        "type": notification_type,
        "title": title,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "priority": priority,
        "sender": current_user.email,
    }

    sent_count = await manager.broadcast(notification)

    logger.info(
        f"Broadcast notification sent by {current_user.email}",
        extra={
            "event_type": "broadcast_notification",
            "sender_id": str(current_user.id),
            "sent_count": sent_count,
            "notification_type": notification_type,
        },
    )

    return {
        "success": True,
        "sent_count": sent_count,
        "message": f"Notification sent to {sent_count} connections",
    }
