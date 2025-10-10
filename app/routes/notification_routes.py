import json
from datetime import datetime, timedelta, timezone
import uuid
from app.dependencies import get_db
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from app.models.rbac_model import Role
from app.models.user_model import User
from app.models.notification_model import Notification
from app.services.notification_sse import manager
from app.utils.permission_checker import require_permission
from app.utils.logging_config import get_logger
import asyncio
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import and_, func, update, delete
from app.utils.security import SessionManager, TokenManager, get_current_user
from app.schemas.notification_schema import (
    NotificationResponse,
    NotificationUpdate,
    NotificationBatchUpdate,
    NotificationStats,
)
from app.utils.pagination import (
    PaginatedResponse,
    PaginationParams,
    get_pagination_params,
)
from typing import Optional, List
from uuid import UUID

logger = get_logger(__name__)
router = APIRouter(prefix="/notifications", tags=["Notifications"])


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
                        except Exception as auth_error:
                            # Transient error during auth check (DB, network, etc.) - log and retry later
                            logger.error(
                                f"Transient authorization check error for user {user_id}: {auth_error}",
                                extra={
                                    "event_type": "sse_auth_check_transient_error",
                                    "user_id": user_id,
                                    "error": str(auth_error),
                                },
                                exc_info=True,
                            )
                            # don't update last_auth_check so we will retry sooner on next loop
                            is_authorized = True  # treat as authorized for now to avoid dropping connection

                        if not is_authorized:
                            # Before terminating, check if token itself is expired/invalid. If so, close.
                            token_invalid_or_expired = False
                            try:
                                payload = TokenManager.decode_token(access_token)
                                token_exp = payload.get("exp")
                                if token_exp:
                                    token_expiry = datetime.fromtimestamp(
                                        token_exp, tz=timezone.utc
                                    )
                                    if datetime.now(timezone.utc) >= token_expiry:
                                        token_invalid_or_expired = True
                            except Exception:
                                # Token invalid or decoding failed
                                token_invalid_or_expired = True

                            logger.warning(
                                f"SSE authorization lost for user {user_id} (token_issue={token_invalid_or_expired})",
                                extra={
                                    "event_type": "sse_authorization_lost",
                                    "user_id": user_id,
                                    "token_issue": token_invalid_or_expired,
                                },
                            )

                            # Send termination event if token expired/invalid or permissions/session explicitly revoked
                            termination_event = {
                                "type": "connection_terminated",
                                "reason": "authorization_lost",
                                "message": "Your session is no longer authorized",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }

                            yield f"data: {json.dumps(termination_event)}\n\n"

                            # If token was invalid/expired, break immediately. Otherwise break as well since authorization was lost.
                            break
                        else:
                            # Authorization OK (or transient error assumed); update last check time
                            last_auth_check = current_time

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


@router.get("/", response_model=PaginatedResponse[NotificationResponse])
async def get_user_notifications(
    request: Request,
    pagination: PaginationParams = Depends(get_pagination_params),
    is_read: Optional[bool] = None,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get paginated list of notifications for the current user.

    Query Parameters:
        - page: Page number (default: 1)
        - page_size: Items per page (default: 20, max: 100)
        - is_read: Filter by read status (optional)
    """
    user_id = str(current_user.id)

    logger.info(
        f"Fetching notifications for user {user_id}",
        extra={
            "event_type": "fetch_notifications",
            "user_id": user_id,
            "page": pagination.page,
            "page_size": pagination.page_size,
            "is_read_filter": is_read,
        },
    )

    try:
        # Build query
        query = select(Notification).where(Notification.user_id == current_user.id)

        # Apply filters
        if is_read is not None:
            query = query.where(Notification.is_read == is_read)

        # Order by created_at desc (newest first)
        query = query.order_by(Notification.created_at.desc())

        # Get total count
        count_query = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == current_user.id)
        )
        if is_read is not None:
            count_query = count_query.where(Notification.is_read == is_read)

        total_result = await db.execute(count_query)
        total_items = total_result.scalar()

        # Apply pagination
        offset = (pagination.page - 1) * pagination.page_size
        query = query.offset(offset).limit(pagination.page_size)

        # Execute query
        result = await db.execute(query)
        notifications = result.scalars().all()

        # Calculate pagination metadata
        total_pages = (total_items + pagination.page_size - 1) // pagination.page_size
        has_next = pagination.page < total_pages
        has_prev = pagination.page > 1

        logger.info(
            f"Retrieved {len(notifications)} notifications for user {user_id}",
            extra={
                "event_type": "notifications_retrieved",
                "user_id": user_id,
                "count": len(notifications),
                "total": total_items,
            },
        )

        return PaginatedResponse(
            items=notifications,
            total_items=total_items,
            total_pages=total_pages,
            current_page=pagination.page,
            page_size=pagination.page_size,
            has_next=has_next,
            has_prev=has_prev,
        )

    except Exception as e:
        logger.error(
            f"Error fetching notifications for user {user_id}: {str(e)}",
            extra={
                "event_type": "fetch_notifications_error",
                "user_id": user_id,
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch notifications",
        )


@router.get("/stats", response_model=NotificationStats)
async def get_notification_stats(
    request: Request,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get notification statistics for the current user.
    Returns total, read, and unread counts.
    """
    user_id = str(current_user.id)

    try:
        # Get total count
        total_result = await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == current_user.id)
        )
        total_notifications = total_result.scalar()

        # Get unread count
        unread_result = await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                and_(
                    Notification.user_id == current_user.id,
                    Notification.is_read == False,
                )
            )
        )
        unread_count = unread_result.scalar()

        # Calculate read count
        read_count = total_notifications - unread_count

        logger.info(
            f"Notification stats for user {user_id}: total={total_notifications}, unread={unread_count}",
            extra={
                "event_type": "notification_stats",
                "user_id": user_id,
                "total": total_notifications,
                "unread": unread_count,
            },
        )

        return NotificationStats(
            total_notifications=total_notifications,
            unread_count=unread_count,
            read_count=read_count,
        )

    except Exception as e:
        logger.error(
            f"Error fetching notification stats for user {user_id}: {str(e)}",
            extra={
                "event_type": "notification_stats_error",
                "user_id": user_id,
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch notification statistics",
        )


@router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification_by_id(
    notification_id: UUID,
    request: Request,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a specific notification by ID.
    Only the notification owner can access it.
    """
    user_id = str(current_user.id)

    try:
        # Fetch notification
        result = await db.execute(
            select(Notification).where(
                and_(
                    Notification.id == notification_id,
                    Notification.user_id == current_user.id,
                )
            )
        )
        notification = result.scalar_one_or_none()

        if not notification:
            logger.warning(
                f"Notification {notification_id} not found for user {user_id}",
                extra={
                    "event_type": "notification_not_found",
                    "user_id": user_id,
                    "notification_id": str(notification_id),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        logger.info(
            f"Retrieved notification {notification_id} for user {user_id}",
            extra={
                "event_type": "notification_retrieved",
                "user_id": user_id,
                "notification_id": str(notification_id),
            },
        )

        return notification

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching notification {notification_id} for user {user_id}: {str(e)}",
            extra={
                "event_type": "fetch_notification_error",
                "user_id": user_id,
                "notification_id": str(notification_id),
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch notification",
        )


@router.patch("/{notification_id}", response_model=NotificationResponse)
async def update_notification(
    notification_id: UUID,
    notification_data: NotificationUpdate,
    request: Request,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update a notification's read status.
    Only the notification owner can update it.
    """
    user_id = str(current_user.id)

    try:
        # Fetch notification
        result = await db.execute(
            select(Notification).where(
                and_(
                    Notification.id == notification_id,
                    Notification.user_id == current_user.id,
                )
            )
        )
        notification = result.scalar_one_or_none()

        if not notification:
            logger.warning(
                f"Notification {notification_id} not found for user {user_id}",
                extra={
                    "event_type": "notification_not_found_for_update",
                    "user_id": user_id,
                    "notification_id": str(notification_id),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        # Update notification
        old_status = notification.is_read
        notification.is_read = notification_data.is_read

        await db.commit()
        await db.refresh(notification)

        logger.info(
            f"Updated notification {notification_id} for user {user_id}: {old_status} -> {notification_data.is_read}",
            extra={
                "event_type": "notification_updated",
                "user_id": user_id,
                "notification_id": str(notification_id),
                "old_status": old_status,
                "new_status": notification_data.is_read,
            },
        )

        return notification

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error updating notification {notification_id} for user {user_id}: {str(e)}",
            extra={
                "event_type": "update_notification_error",
                "user_id": user_id,
                "notification_id": str(notification_id),
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update notification",
        )


@router.patch("/batch/update", response_model=dict)
async def batch_update_notifications(
    batch_data: NotificationBatchUpdate,
    request: Request,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Batch update multiple notifications' read status.
    Only the notification owner can update their notifications.
    """
    user_id = str(current_user.id)
    notification_ids = batch_data.notification_ids

    logger.info(
        f"Batch updating {len(notification_ids)} notifications for user {user_id}",
        extra={
            "event_type": "batch_update_notifications_attempt",
            "user_id": user_id,
            "count": len(notification_ids),
            "is_read": batch_data.is_read,
        },
    )

    try:
        # Update notifications
        result = await db.execute(
            update(Notification)
            .where(
                and_(
                    Notification.id.in_(notification_ids),
                    Notification.user_id == current_user.id,
                )
            )
            .values(is_read=batch_data.is_read)
        )

        updated_count = result.rowcount

        await db.commit()

        logger.info(
            f"Batch updated {updated_count} notifications for user {user_id}",
            extra={
                "event_type": "batch_update_notifications_success",
                "user_id": user_id,
                "updated_count": updated_count,
                "requested_count": len(notification_ids),
            },
        )

        return {
            "success": True,
            "updated_count": updated_count,
            "message": f"Successfully updated {updated_count} notification(s)",
        }

    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error batch updating notifications for user {user_id}: {str(e)}",
            extra={
                "event_type": "batch_update_notifications_error",
                "user_id": user_id,
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to batch update notifications",
        )


@router.post("/mark-all-read", response_model=dict)
async def mark_all_notifications_read(
    request: Request,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Mark all notifications as read for the current user.
    """
    user_id = str(current_user.id)

    try:
        # Update all unread notifications
        result = await db.execute(
            update(Notification)
            .where(
                and_(
                    Notification.user_id == current_user.id,
                    Notification.is_read == False,
                )
            )
            .values(is_read=True)
        )

        updated_count = result.rowcount

        await db.commit()

        logger.info(
            f"Marked {updated_count} notifications as read for user {user_id}",
            extra={
                "event_type": "mark_all_read",
                "user_id": user_id,
                "updated_count": updated_count,
            },
        )

        return {
            "success": True,
            "updated_count": updated_count,
            "message": f"Successfully marked {updated_count} notification(s) as read",
        }

    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error marking all notifications as read for user {user_id}: {str(e)}",
            extra={
                "event_type": "mark_all_read_error",
                "user_id": user_id,
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark all notifications as read",
        )


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: UUID,
    request: Request,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a specific notification.
    Only the notification owner can delete it.
    """
    user_id = str(current_user.id)

    try:
        # Check if notification exists and belongs to user
        result = await db.execute(
            select(Notification).where(
                and_(
                    Notification.id == notification_id,
                    Notification.user_id == current_user.id,
                )
            )
        )
        notification = result.scalar_one_or_none()

        if not notification:
            logger.warning(
                f"Notification {notification_id} not found for deletion by user {user_id}",
                extra={
                    "event_type": "notification_not_found_for_delete",
                    "user_id": user_id,
                    "notification_id": str(notification_id),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        # Delete notification
        await db.delete(notification)
        await db.commit()

        logger.info(
            f"Deleted notification {notification_id} for user {user_id}",
            extra={
                "event_type": "notification_deleted",
                "user_id": user_id,
                "notification_id": str(notification_id),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error deleting notification {notification_id} for user {user_id}: {str(e)}",
            extra={
                "event_type": "delete_notification_error",
                "user_id": user_id,
                "notification_id": str(notification_id),
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete notification",
        )


@router.delete("/batch/delete", response_model=dict)
async def batch_delete_notifications(
    notification_ids: List[UUID],
    request: Request,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Batch delete multiple notifications.
    Only the notification owner can delete their notifications.
    """
    user_id = str(current_user.id)

    logger.info(
        f"Batch deleting {len(notification_ids)} notifications for user {user_id}",
        extra={
            "event_type": "batch_delete_notifications_attempt",
            "user_id": user_id,
            "count": len(notification_ids),
        },
    )

    try:
        # Delete notifications
        result = await db.execute(
            delete(Notification).where(
                and_(
                    Notification.id.in_(notification_ids),
                    Notification.user_id == current_user.id,
                )
            )
        )

        deleted_count = result.rowcount

        await db.commit()

        logger.info(
            f"Batch deleted {deleted_count} notifications for user {user_id}",
            extra={
                "event_type": "batch_delete_notifications_success",
                "user_id": user_id,
                "deleted_count": deleted_count,
                "requested_count": len(notification_ids),
            },
        )

        return {
            "success": True,
            "deleted_count": deleted_count,
            "message": f"Successfully deleted {deleted_count} notification(s)",
        }

    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error batch deleting notifications for user {user_id}: {str(e)}",
            extra={
                "event_type": "batch_delete_notifications_error",
                "user_id": user_id,
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to batch delete notifications",
        )


@router.delete("/clear-all", response_model=dict)
async def clear_all_notifications(
    request: Request,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete all notifications for the current user.
    Use with caution - this action cannot be undone.
    """
    user_id = str(current_user.id)

    try:
        # Delete all user's notifications
        result = await db.execute(
            delete(Notification).where(Notification.user_id == current_user.id)
        )

        deleted_count = result.rowcount

        await db.commit()

        logger.info(
            f"Cleared all {deleted_count} notifications for user {user_id}",
            extra={
                "event_type": "clear_all_notifications",
                "user_id": user_id,
                "deleted_count": deleted_count,
            },
        )

        return {
            "success": True,
            "deleted_count": deleted_count,
            "message": f"Successfully cleared {deleted_count} notification(s)",
        }

    except Exception as e:
        await db.rollback()
        logger.error(
            f"Error clearing all notifications for user {user_id}: {str(e)}",
            extra={
                "event_type": "clear_all_notifications_error",
                "user_id": user_id,
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear all notifications",
        )
