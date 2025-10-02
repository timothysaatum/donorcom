import json
from datetime import datetime, timedelta, timezone
import uuid
from app.dependencies import get_db
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse
from app.models.rbac import Role
from app.models.user import User
from app.services.notification_sse import manager
from app.utils.permission_checker import require_permission
from app.utils.logging_config import get_logger
import asyncio
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.utils.security import SessionManager, TokenManager

logger = get_logger(__name__)
router = APIRouter(prefix="/notifications", tags=["Notifications"])


# @router.get("/sse/stream")
# async def sse_notifications(
#     request: Request,
#     db=Depends(get_db),
#     current_user=Depends(
#         require_permission(
#             "facility.manage",
#             "laboratory.manage",
#             "blood.inventory.manage",
#             validate_session=True,
#         )
#     ),
# ):
#     """
#     SSE endpoint for real-time notifications streaming.
#     Maintains a persistent connection to push server events to the client.
#     """
#     user_id = str(current_user.id)
#     event_queue = manager.add_sse_connection(user_id)

#     logger.info(
#         f"SSE connection established for user {user_id}",
#         extra={
#             "event_type": "sse_connection_established",
#             "user_id": user_id,
#             "user_email": current_user.email,
#         },
#     )

#     async def event_stream():
#         """Generator function that yields SSE-formatted events"""
#         try:
#             # Send initial connection success event
#             connection_event = {
#                 "type": "connection_established",
#                 "message": "Successfully connected to notification stream",
#                 "timestamp": datetime.now(timezone.utc).isoformat(),
#                 "user_id": user_id,
#             }
#             yield f"data: {json.dumps(connection_event)}\n\n"

#             # Send heartbeat every 30 seconds to keep connection alive
#             heartbeat_task = asyncio.create_task(send_heartbeat())

#             try:
#                 while True:
#                     # Check if client disconnected
#                     if await request.is_disconnected():
#                         logger.info(
#                             f"SSE client {user_id} disconnected",
#                             extra={
#                                 "event_type": "sse_client_disconnected",
#                                 "user_id": user_id,
#                             },
#                         )
#                         break

#                     try:
#                         # Wait for event with timeout (for heartbeat)
#                         event = await asyncio.wait_for(event_queue.get(), timeout=30.0)

#                         # Format and send the event
#                         yield f"data: {json.dumps(event)}\n\n"

#                         logger.debug(
#                             f"SSE event sent to user {user_id}",
#                             extra={
#                                 "event_type": "sse_event_sent",
#                                 "user_id": user_id,
#                                 "notification_type": event.get("type"),
#                             },
#                         )

#                     except asyncio.TimeoutError:
#                         # Send heartbeat (keep-alive)
#                         heartbeat = {
#                             "type": "heartbeat",
#                             "timestamp": datetime.now(timezone.utc).isoformat(),
#                         }
#                         yield f": heartbeat\n\n"

#                     except Exception as e:
#                         logger.error(
#                             f"SSE error for user {user_id}: {e}",
#                             extra={
#                                 "event_type": "sse_stream_error",
#                                 "user_id": user_id,
#                                 "error": str(e),
#                             },
#                             exc_info=True,
#                         )
#                         break

#             finally:
#                 heartbeat_task.cancel()

#         except Exception as e:
#             logger.error(
#                 f"SSE stream initialization error for user {user_id}: {e}",
#                 extra={
#                     "event_type": "sse_initialization_error",
#                     "user_id": user_id,
#                     "error": str(e),
#                 },
#                 exc_info=True,
#             )
#         finally:
#             # Clean up connection
#             manager.disconnect_sse(user_id, event_queue)
#             logger.info(
#                 f"SSE connection closed for user {user_id}",
#                 extra={"event_type": "sse_connection_closed", "user_id": user_id},
#             )

#     async def send_heartbeat():
#         """Background task to send periodic heartbeats"""
#         while True:
#             await asyncio.sleep(30)


#     return StreamingResponse(
#         event_stream(),
#         media_type="text/event-stream",
#         headers={
#             "Cache-Control": "no-cache",
#             "Connection": "keep-alive",
#             "X-Accel-Buffering": "no",  # Disable nginx buffering
#         },
#     )
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
    SSE endpoint for real-time notifications streaming with enhanced security.
    Maintains a persistent connection with periodic authorization checks.
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

    async def verify_authorization() -> bool:
        """
        Verify user still has required permissions and valid session.
        Returns True if authorized, False otherwise.
        """
        try:
            # Re-fetch user to get current permissions
            result = await db.execute(
                select(User)
                .options(selectinload(User.roles).selectinload(Role.permissions))
                .where(User.id == current_user.id)
            )
            user = result.scalar_one_or_none()

            if not user:
                logger.warning(
                    f"SSE auth check failed - user not found: {user_id}",
                    extra={"event_type": "sse_auth_user_not_found", "user_id": user_id},
                )
                return False

            # Check if user is still active
            if not user.is_active or not user.status or user.is_locked:
                logger.warning(
                    f"SSE auth check failed - account inactive: {user_id}",
                    extra={
                        "event_type": "sse_auth_inactive_account",
                        "user_id": user_id,
                    },
                )
                return False

            # Verify user still has required permissions
            required_perms = [
                "facility.manage",
                "laboratory.manage",
                "blood.inventory.manage",
            ]
            has_permission = any(user.has_permission(perm) for perm in required_perms)

            if not has_permission:
                logger.warning(
                    f"SSE auth check failed - insufficient permissions: {user_id}",
                    extra={
                        "event_type": "sse_auth_permission_denied",
                        "user_id": user_id,
                        "required_permissions": required_perms,
                    },
                )
                return False

            # Validate session from authorization header
            authorization_header = request.headers.get("authorization")
            if not authorization_header or not authorization_header.startswith(
                "Bearer "
            ):
                return False

            token = authorization_header.split(" ")[1]
            payload = TokenManager.decode_token(token)

            if not payload:
                return False

            session_id = payload.get("sid")
            if session_id:
                session = await SessionManager.validate_session(
                    db=db, session_id=uuid.UUID(session_id), request=request
                )
                if not session:
                    logger.warning(
                        f"SSE auth check failed - invalid session: {user_id}",
                        extra={
                            "event_type": "sse_auth_invalid_session",
                            "user_id": user_id,
                            "session_id": session_id,
                        },
                    )
                    return False

            return True

        except Exception as e:
            logger.error(
                f"SSE authorization check error for user {user_id}: {e}",
                extra={
                    "event_type": "sse_auth_check_error",
                    "user_id": user_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            return False

    async def send_heartbeat():
        """Periodic heartbeat with authorization check"""
        while True:
            await asyncio.sleep(30)

    async def event_stream():
        """Generator function that yields SSE-formatted events with security checks"""
        try:
            # Send initial connection success event
            connection_event = {
                "type": "connection_established",
                "message": "Successfully connected to notification stream",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_id": user_id,
            }
            yield f"data: {json.dumps(connection_event)}\n\n"

            heartbeat_task = asyncio.create_task(send_heartbeat())
            last_auth_check = datetime.now(timezone.utc)
            auth_check_interval = timedelta(minutes=5)  # Re-check every 5 minutes

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

                    # Periodic authorization re-check
                    current_time = datetime.now(timezone.utc)
                    if current_time - last_auth_check > auth_check_interval:
                        is_authorized = await verify_authorization()
                        if not is_authorized:
                            logger.warning(
                                f"SSE authorization lost for user {user_id}",
                                extra={
                                    "event_type": "sse_authorization_lost",
                                    "user_id": user_id,
                                },
                            )
                            # Send termination event
                            termination_event = {
                                "type": "connection_terminated",
                                "reason": "authorization_lost",
                                "message": "Your session is no longer authorized",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                            yield f"data: {json.dumps(termination_event)}\n\n"
                            break
                        last_auth_check = current_time

                    try:
                        # Wait for event with timeout
                        event = await asyncio.wait_for(event_queue.get(), timeout=30.0)

                        # Additional security check before sending sensitive events
                        if event.get("type") not in [
                            "heartbeat",
                            "connection_established",
                        ]:
                            # Quick permission check for critical events
                            is_authorized = await verify_authorization()
                            if not is_authorized:
                                logger.warning(
                                    f"Event blocked due to authorization loss: {user_id}",
                                    extra={
                                        "event_type": "sse_event_blocked",
                                        "user_id": user_id,
                                        "event_type_blocked": event.get("type"),
                                    },
                                )
                                break

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
