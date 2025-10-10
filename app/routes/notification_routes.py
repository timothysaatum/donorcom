import json
from datetime import datetime, timedelta, timezone
import uuid
from app.dependencies import get_db
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse
from app.models.rbac_model import Role
from app.models.user_model import User
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
    access_token: str,  # Renamed from 'token' for clarity
    db=Depends(get_db),
):
    """
    SSE endpoint for real-time notifications streaming with enhanced security.
    Maintains a persistent connection with periodic authorization checks.

    Query Parameters:
        access_token: JWT access token for authentication (required since SSE can't use headers)

    Example:
        GET /notifications/sse/stream?access_token=your_jwt_token_here

    Security Measures:
    - Token is validated immediately and not logged
    - Short-lived tokens recommended (use refresh mechanism)
    - Connection auto-terminates on token expiry
    - IP validation against token's original IP (optional)
    - Rate limiting recommended at proxy/gateway level
    """

    # Security: Get client IP for validation
    client_ip = request.client.host if request.client else "unknown"

    # Validate token and get user
    try:
        # Decode token without logging it
        payload = TokenManager.decode_token(access_token)
        user_id_from_token = payload.get("sub")
        session_id = payload.get("sid")
        token_exp = payload.get("exp")

        if not user_id_from_token:
            logger.warning(
                "SSE connection denied - invalid token",
                extra={
                    "event_type": "sse_invalid_token",
                    "ip_address": client_ip,
                },
            )
            # Return generic error to avoid information leakage
            return StreamingResponse(
                iter(
                    [
                        f"data: {json.dumps({'type': 'error', 'message': 'Authentication failed'})}\n\n"
                    ]
                ),
                media_type="text/event-stream",
                status_code=401,
            )

        # Check token expiration
        if token_exp:
            token_expiry = datetime.fromtimestamp(token_exp, tz=timezone.utc)
            if datetime.now(timezone.utc) >= token_expiry:
                logger.warning(
                    "SSE connection denied - token expired",
                    extra={
                        "event_type": "sse_token_expired",
                        "user_id": user_id_from_token,
                        "ip_address": client_ip,
                    },
                )
                return StreamingResponse(
                    iter(
                        [
                            f"data: {json.dumps({'type': 'error', 'message': 'Token expired'})}\n\n"
                        ]
                    ),
                    media_type="text/event-stream",
                    status_code=401,
                )

        # Fetch user with permissions
        result = await db.execute(
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.id == uuid.UUID(user_id_from_token))
        )
        current_user = result.scalar_one_or_none()

        if not current_user:
            logger.warning(
                "SSE connection denied - user not found",
                extra={
                    "event_type": "sse_user_not_found",
                    "user_id": user_id_from_token,
                    "ip_address": client_ip,
                },
            )
            return StreamingResponse(
                iter(
                    [
                        f"data: {json.dumps({'type': 'error', 'message': 'Authentication failed'})}\n\n"
                    ]
                ),
                media_type="text/event-stream",
                status_code=401,
            )

        # Check user status
        if (
            not current_user.is_active
            or not current_user.status
            or current_user.is_locked
        ):
            logger.warning(
                "SSE connection denied - account inactive",
                extra={
                    "event_type": "sse_account_inactive",
                    "user_id": user_id_from_token,
                    "ip_address": client_ip,
                },
            )
            return StreamingResponse(
                iter(
                    [
                        f"data: {json.dumps({'type': 'error', 'message': 'Account inactive'})}\n\n"
                    ]
                ),
                media_type="text/event-stream",
                status_code=403,
            )

        # Check permissions
        required_perms = [
            "facility.manage",
            "laboratory.manage",
            "blood.inventory.manage",
        ]
        has_permission = any(
            current_user.has_permission(perm) for perm in required_perms
        )

        if not has_permission:
            logger.warning(
                "SSE connection denied - insufficient permissions",
                extra={
                    "event_type": "sse_permission_denied",
                    "user_id": user_id_from_token,
                    "ip_address": client_ip,
                },
            )
            return StreamingResponse(
                iter(
                    [
                        f"data: {json.dumps({'type': 'error', 'message': 'Insufficient permissions'})}\n\n"
                    ]
                ),
                media_type="text/event-stream",
                status_code=403,
            )

        # Validate session if present
        if session_id:
            session = await SessionManager.validate_session(
                db=db, session_id=uuid.UUID(session_id), request=request
            )
            if not session:
                logger.warning(
                    "SSE connection denied - invalid session",
                    extra={
                        "event_type": "sse_invalid_session",
                        "user_id": user_id_from_token,
                        "session_id": session_id,
                        "ip_address": client_ip,
                    },
                )
                return StreamingResponse(
                    iter(
                        [
                            f"data: {json.dumps({'type': 'error', 'message': 'Invalid session'})}\n\n"
                        ]
                    ),
                    media_type="text/event-stream",
                    status_code=401,
                )

            # Security: Check if IP matches session IP (optional strict mode)
            # Uncomment to enable strict IP validation
            # if session.ip_address and session.ip_address != client_ip:
            #     logger.warning(
            #         "SSE connection denied - IP mismatch",
            #         extra={
            #             "event_type": "sse_ip_mismatch",
            #             "user_id": user_id_from_token,
            #             "expected_ip": session.ip_address,
            #             "actual_ip": client_ip,
            #         },
            #     )
            #     return StreamingResponse(
            #         iter(
            #             [
            #                 f"data: {json.dumps({'type': 'error', 'message': 'IP validation failed'})}\n\n"
            #             ]
            #         ),
            #         media_type="text/event-stream",
            #         status_code=403,
            #     )

    except ValueError as e:
        # Token decode error
        logger.warning(
            f"SSE authentication error - invalid token format: {str(e)}",
            extra={
                "event_type": "sse_auth_error",
                "ip_address": client_ip,
                "error_type": "invalid_token_format",
            },
        )
        return StreamingResponse(
            iter(
                [
                    f"data: {json.dumps({'type': 'error', 'message': 'Authentication failed'})}\n\n"
                ]
            ),
            media_type="text/event-stream",
            status_code=401,
        )
    except Exception as e:
        logger.error(
            f"SSE authentication error: {str(e)}",
            extra={
                "event_type": "sse_auth_error",
                "error": str(e),
                "ip_address": client_ip,
            },
            exc_info=True,
        )
        return StreamingResponse(
            iter(
                [
                    f"data: {json.dumps({'type': 'error', 'message': 'Authentication failed'})}\n\n"
                ]
            ),
            media_type="text/event-stream",
            status_code=500,
        )

    user_id = str(current_user.id)

    # Security: Limit concurrent connections per user
    existing_connections = manager.get_user_connection_count(user_id)
    MAX_CONNECTIONS_PER_USER = 3  # Adjust as needed

    if existing_connections >= MAX_CONNECTIONS_PER_USER:
        logger.warning(
            f"SSE connection denied - max connections reached for user {user_id}",
            extra={
                "event_type": "sse_max_connections_reached",
                "user_id": user_id,
                "existing_connections": existing_connections,
                "ip_address": client_ip,
            },
        )
        return StreamingResponse(
            iter(
                [
                    f"data: {json.dumps({'type': 'error', 'message': 'Maximum concurrent connections reached'})}\n\n"
                ]
            ),
            media_type="text/event-stream",
            status_code=429,
        )

    event_queue = await manager.add_sse_connection(user_id)

    logger.info(
        f"SSE connection established for user {user_id}",
        extra={
            "event_type": "sse_connection_established",
            "user_id": user_id,
            "user_email": current_user.email,
            "ip_address": client_ip,
            "token_expiry": token_exp,
        },
    )

    async def verify_authorization() -> bool:
        """
        Verify user still has required permissions and valid session.
        Returns True if authorized, False otherwise.

        Security: Re-validates token and checks for revocation
        """
        try:
            # Re-validate the token (checks expiration and signature)
            try:
                payload = TokenManager.decode_token(access_token)
                if not payload or payload.get("sub") != user_id:
                    return False

                # Check if token has expired
                token_exp = payload.get("exp")
                if token_exp:
                    token_expiry = datetime.fromtimestamp(token_exp, tz=timezone.utc)
                    if datetime.now(timezone.utc) >= token_expiry:
                        logger.warning(
                            f"SSE auth check failed - token expired: {user_id}",
                            extra={
                                "event_type": "sse_token_expired_during_stream",
                                "user_id": user_id,
                            },
                        )
                        return False

            except Exception as e:
                logger.warning(
                    f"SSE auth check failed - token validation error: {user_id}",
                    extra={
                        "event_type": "sse_token_validation_error",
                        "user_id": user_id,
                        "error": str(e),
                    },
                )
                return False

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

            # Validate session if present
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
        try:
            while True:
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            # Task was cancelled, exit gracefully
            pass

    async def event_stream():
        """Generator function that yields SSE-formatted events with security checks"""
        heartbeat_task = None
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

            while True:
                try:
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
                        try:
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
                        except Exception as auth_error:
                            logger.error(
                                f"Authorization check error for user {user_id}: {auth_error}",
                                extra={
                                    "event_type": "sse_auth_check_error",
                                    "user_id": user_id,
                                    "error": str(auth_error),
                                },
                            )
                            # Continue on auth check errors, don't break the stream

                    try:
                        # Wait for event with timeout
                        event = await asyncio.wait_for(event_queue.get(), timeout=30.0)

                        # Additional security check before sending sensitive events
                        if event.get("type") not in [
                            "heartbeat",
                            "connection_established",
                        ]:
                            try:
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
                            except Exception as auth_error:
                                logger.error(
                                    f"Event authorization check error: {auth_error}",
                                    extra={
                                        "event_type": "sse_event_auth_error",
                                        "user_id": user_id,
                                    },
                                )
                                # Don't send the event if auth check fails
                                continue

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
                        # Send heartbeat (keep-alive) - this is critical for maintaining connection
                        try:
                            yield ": heartbeat\n\n"
                            logger.debug(
                                f"Heartbeat sent to user {user_id}",
                                extra={
                                    "event_type": "sse_heartbeat_sent",
                                    "user_id": user_id,
                                },
                            )
                        except Exception as heartbeat_error:
                            logger.error(
                                f"Failed to send heartbeat to user {user_id}: {heartbeat_error}",
                                extra={
                                    "event_type": "sse_heartbeat_error",
                                    "user_id": user_id,
                                    "error": str(heartbeat_error),
                                },
                            )
                            # If we can't send heartbeat, connection is likely dead
                            break

                    except asyncio.CancelledError:
                        logger.info(
                            f"SSE stream cancelled for user {user_id}",
                            extra={
                                "event_type": "sse_stream_cancelled",
                                "user_id": user_id,
                            },
                        )
                        break

                    except Exception as e:
                        logger.error(
                            f"SSE event processing error for user {user_id}: {e}",
                            extra={
                                "event_type": "sse_event_error",
                                "user_id": user_id,
                                "error": str(e),
                            },
                            exc_info=True,
                        )
                        # Don't break on event processing errors, continue stream
                        continue

                except Exception as loop_error:
                    logger.error(
                        f"SSE loop error for user {user_id}: {loop_error}",
                        extra={
                            "event_type": "sse_loop_error",
                            "user_id": user_id,
                            "error": str(loop_error),
                        },
                        exc_info=True,
                    )
                    # Break on unexpected loop errors
                    break

        except GeneratorExit:
            logger.info(
                f"SSE generator exit for user {user_id}",
                extra={
                    "event_type": "sse_generator_exit",
                    "user_id": user_id,
                },
            )
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
            # Clean up heartbeat task
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            # Clean up connection
            await manager.disconnect_sse(user_id, event_queue)
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
