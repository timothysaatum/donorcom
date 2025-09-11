import uuid
from app.models.user import UserSession
from fastapi import (
    APIRouter,
    Depends,
    BackgroundTasks,
    HTTPException,
    Response,
    Request,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime
import time
import os
from app.models import User
from app.schemas.user import AuthResponse, LoginSchema
from app.dependencies import get_db
from app.utils.email_verification import send_verification_email
from app.utils.security import (
    TokenManager,
    SessionManager,  # New import
    get_current_user,
    authenticate_user,
    cleanup_expired_refresh_tokens,
)
from app.utils.data_wrapper import DataWrapper
from app.utils.logging_config import (
    get_logger,
    log_audit_event,
    log_security_event,
    log_function_call,
)
from app.utils.ip_address_finder import get_client_ip, get_user_agent

# JWT and Token Configuration
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS"))

# Environment detection
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT.lower() in ["production", "prod"]

logger = get_logger(__name__)

# Authentication Router
router = APIRouter(prefix="/users/auth", tags=["auth"])


def set_refresh_token_cookie(
    response: Response, refresh_token: str, request: Request = None
):
    """Helper function to set refresh token cookie with proper security settings"""
    logger.debug("Setting refresh token cookie")

    is_secure = IS_PRODUCTION

    if request:
        is_secure = request.url.scheme == "https" or IS_PRODUCTION

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=is_secure,
        samesite="none" if is_secure else "lax",
        max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRE_DAYS,
        domain=None,
    )

    logger.info(
        "Refresh token cookie set successfully",
        extra={
            "extra_fields": {
                "secure_context": is_secure,
                "samesite_policy": "none" if is_secure else "lax",
                "action": "cookie_set",
            }
        },
    )


@router.post("/login", response_model=DataWrapper[AuthResponse])
@log_function_call(include_args=False, level="INFO")
async def login(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    credentials: LoginSchema,
    db: AsyncSession = Depends(get_db),
):
    """Enhanced login endpoint with session management integration"""
    start_time = time.time()
    email = credentials.email

    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    logger.info(
        f"Login attempt for email: {email}",
        extra={
            "extra_fields": {
                "email": email,
                "client_ip": client_ip,
                "user_agent": user_agent,
                "action": "login_attempt",
            }
        },
    )

    try:
        # Clean up expired refresh tokens periodically
        background_tasks.add_task(cleanup_expired_refresh_tokens, db)

        # Authenticate user with enhanced security
        auth_success, user, error_message = await authenticate_user(
            db=db,
            email=email,
            password=credentials.password,
            ip_address=client_ip,
            user_agent=user_agent,
        )
        if not auth_success:
            if user and hasattr(user, "is_verified") and not user.is_verified:
                background_tasks.add_task(
                    send_verification_email,
                    email,
                    (
                        user.verification_token
                        if hasattr(user, "verification_token")
                        else None
                    ),
                )

                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": "Email not verified. A new verification link has been sent to your email."
                    },
                )

            raise HTTPException(status_code=400, detail=error_message)

        # Create user session with enhanced tracking
        session = await SessionManager.create_session(
            db=db, user_id=user.id, request=request, login_method="password"
        )

        # Create tokens with session reference
        access_token = TokenManager.create_access_token(
            data={"sub": str(user.id)}, session_id=session.id
        )
        refresh_token = TokenManager.create_refresh_token(user.id)

        # Create refresh token database record
        await TokenManager.create_refresh_token_record(
            db=db,
            user_id=user.id,
            token=refresh_token,
            device_info=user_agent,
            ip_address=client_ip,
        )

        # Set refresh token cookie
        set_refresh_token_cookie(response, refresh_token, request)

        duration_ms = (time.time() - start_time) * 1000

        # Create auth response
        from app.schemas.user import UserWithFacility

        user_data = UserWithFacility.from_db_user(user).model_dump()

        auth_response = AuthResponse(access_token=access_token, user=user_data)

        logger.info(
            f"Login successful for user: {email}",
            extra={
                "extra_fields": {
                    "user_id": str(user.id),
                    "email": email,
                    "client_ip": client_ip,
                    "session_id": str(session.id),
                    "last_login": (
                        user.last_login.isoformat() if user.last_login else None
                    ),
                    "action": "login_successful",
                    "duration_ms": duration_ms,
                }
            },
        )

        log_audit_event(
            action="login",
            resource_type="user_session",
            resource_id=str(user.id),
            new_values={
                "last_login": user.last_login.isoformat() if user.last_login else None
            },
            user_id=str(user.id),
        )

        return {"data": auth_response}

    except HTTPException:
        raise
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Login failed due to unexpected error",
            extra={
                "extra_fields": {
                    "email": email,
                    "client_ip": client_ip,
                    "error": str(e),
                    "duration_ms": duration_ms,
                    "action": "login_error",
                }
            },
            exc_info=True,
        )

        log_security_event(
            event_type="login_error",
            ip_address=client_ip,
            user_agent=user_agent,
            details={"email": email, "error": str(e), "duration_ms": duration_ms},
        )

        raise HTTPException(status_code=500, detail="Login failed")


@router.get("/refresh", response_model=DataWrapper[AuthResponse])
async def refresh_token(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    """Enhanced refresh token endpoint with absolute expiration"""
    start_time = time.time()

    session_data = SessionManager.extract_device_info(request)
    client_ip = session_data.get("client_ip")
    user_agent = session_data.get("user_agent")

    logger.info(
        "Token refresh attempt started",
        extra={
            "event_type": "token_refresh_attempt",
            "client_ip": client_ip,
            "user_agent": user_agent,
        },
    )

    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        log_security_event(
            event_type="token_refresh_failed",
            details={
                "reason": "no_refresh_token",
                "duration_ms": (time.time() - start_time) * 1000,
            },
            ip_address=client_ip,
        )

        logger.warning("Token refresh failed - no refresh token provided")
        raise HTTPException(status_code=401, detail="No refresh token provided")

    try:
        # Validate refresh token
        refresh_token_record = await TokenManager.validate_refresh_token(
            db, refresh_token
        )

        if not refresh_token_record:
            log_security_event(
                event_type="token_refresh_failed",
                details={
                    "reason": "invalid_refresh_token",
                    "duration_ms": (time.time() - start_time) * 1000,
                },
                ip_address=client_ip,
            )

            logger.warning("Token refresh failed - invalid refresh token")
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        # NEW: Check if refresh token has exceeded its absolute expiration
        current_time = datetime.now()
        if current_time > refresh_token_record.absolute_expires_at:
            # Revoke the expired token
            await TokenManager.revoke_refresh_token(db, refresh_token_record.id)

            log_security_event(
                event_type="token_refresh_failed",
                details={
                    "reason": "refresh_token_absolutely_expired",
                    "absolute_expiry": refresh_token_record.absolute_expires_at.isoformat(),
                    "current_time": current_time.isoformat(),
                    "duration_ms": (time.time() - start_time) * 1000,
                },
                ip_address=client_ip,
            )

            logger.warning(
                "Token refresh failed - refresh token has absolutely expired"
            )
            raise HTTPException(
                status_code=401,
                detail="Refresh token has expired. Please log in again.",
            )

        user = refresh_token_record.user
        user_id = user.id

        # Additional user validation
        if not user.is_active or not user.status or user.is_locked:
            log_security_event(
                event_type="token_refresh_failed",
                details={
                    "reason": "user_account_inactive",
                    "user_id": str(user_id),
                    "duration_ms": (time.time() - start_time) * 1000,
                },
                user_id=str(user_id),
                ip_address=client_ip,
            )

            raise HTTPException(status_code=401, detail="User account is inactive")

        # Create new session for token refresh
        session = await SessionManager.create_session(
            db=db, user_id=user_id, request=request, login_method="refresh_token"
        )

        # Create new access token with session reference
        new_access_token = TokenManager.create_access_token(
            data={"sub": str(user_id)}, session_id=session.id
        )

        # UPDATED: Only update the refresh token's last_used_at, don't create a new one
        # This maintains the original absolute expiration time
        refresh_token_record.last_used_at = current_time
        refresh_token_record.usage_count += 1

        # Optional: Update device/IP info if they've changed
        if refresh_token_record.ip_address != client_ip:
            refresh_token_record.ip_address = client_ip
        if refresh_token_record.device_info != user_agent:
            refresh_token_record.device_info = user_agent

        await db.commit()

        # Load user with all relationships
        from sqlalchemy.orm import selectinload
        from app.models.health_facility import Facility

        result = await db.execute(
            select(User)
            .options(
                selectinload(User.roles),
                selectinload(User.facility).selectinload(Facility.blood_bank),
                selectinload(User.work_facility).selectinload(Facility.blood_bank),
            )
            .where(User.id == user_id)
        )
        user_with_relations = result.scalar_one_or_none()

        if not user_with_relations:
            raise HTTPException(status_code=401, detail="User not found")

        # Update last login time
        user_with_relations.last_login = datetime.now()
        await db.commit()

        duration_ms = (time.time() - start_time) * 1000

        log_security_event(
            event_type="token_refresh_success",
            details={
                "duration_ms": duration_ms,
                "new_access_token_created": True,
                "refresh_token_reused": True,
                "refresh_token_usage_count": refresh_token_record.usage_count,
                "refresh_token_absolute_expiry": refresh_token_record.absolute_expires_at.isoformat(),
                "session_id": str(session.id),
            },
            user_id=str(user_id),
            ip_address=client_ip,
        )

        logger.info(
            "Token refresh successful",
            extra={
                "event_type": "token_refresh_success",
                "user_id": str(user_id),
                "session_id": str(session.id),
                "duration_ms": duration_ms,
                "refresh_token_usage_count": refresh_token_record.usage_count,
            },
        )

        # Create auth response
        from app.schemas.user import UserWithFacility

        user_data = UserWithFacility.from_db_user(user_with_relations).model_dump()
        auth_response = AuthResponse(access_token=new_access_token, user=user_data)

        return {"data": auth_response}

    except HTTPException:
        raise
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Token refresh failed due to unexpected error",
            extra={
                "event_type": "token_refresh_error",
                "error": str(e),
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )

        log_security_event(
            event_type="token_refresh_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "duration_ms": duration_ms,
            },
            ip_address=client_ip,
        )

        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enhanced logout endpoint with session termination"""
    start_time = time.time()
    client_ip = get_client_ip(request)
    user_id = str(current_user.id)

    logger.info(
        "Logout attempt started",
        extra={
            "event_type": "logout_attempt",
            "user_id": user_id,
            "client_ip": client_ip,
        },
    )

    try:
        # Get current session ID from token if available
        auth_header = request.headers.get("authorization")
        session_id = None

        if auth_header and auth_header.startswith("Bearer "):
            try:
                token = auth_header.split(" ")[1]
                payload = TokenManager.decode_token(token)
                session_id = payload.get("sid")
            except Exception:
                pass  # Continue with logout even if token parsing fails

        # Terminate current session if identified
        if session_id:
            
            await SessionManager.terminate_session(
                db=db, session_id=uuid.UUID(session_id), reason="user_logout"
            )

        # Get and revoke refresh token
        refresh_token = request.cookies.get("refresh_token")

        if refresh_token:
            refresh_token_record = await TokenManager.validate_refresh_token(
                db, refresh_token
            )
            if refresh_token_record:
                await TokenManager.revoke_refresh_token(db, refresh_token_record.id)
                logger.info(
                    "Refresh token revoked during logout",
                    extra={
                        "event_type": "refresh_token_revoked_logout",
                        "user_id": user_id,
                        "token_id": str(refresh_token_record.id),
                    },
                )

        # Clear cookie
        response.delete_cookie(
            key="refresh_token",
            httponly=True,
            secure=IS_PRODUCTION,
            samesite="none" if IS_PRODUCTION else "lax",
        )

        duration_ms = (time.time() - start_time) * 1000

        log_security_event(
            event_type="logout_success",
            details={
                "duration_ms": duration_ms,
                "cookie_cleared": True,
                "refresh_token_revoked": bool(refresh_token),
                "session_terminated": bool(session_id),
            },
            user_id=user_id,
            ip_address=client_ip,
        )

        log_audit_event(
            action="logout",
            resource_type="user_session",
            resource_id=user_id,
            user_id=user_id,
        )

        logger.info(
            "Logout successful",
            extra={
                "event_type": "logout_success",
                "user_id": user_id,
                "session_id": session_id,
                "duration_ms": duration_ms,
            },
        )

        return {"data": {"message": "Logged out successfully"}}

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Logout failed due to unexpected error",
            extra={
                "event_type": "logout_error",
                "user_id": user_id,
                "error": str(e),
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )

        log_security_event(
            event_type="logout_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "duration_ms": duration_ms,
            },
            user_id=user_id,
            ip_address=client_ip,
        )

        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/logout-all")
async def logout_all_devices(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enhanced logout all devices with comprehensive session termination"""
    start_time = time.time()
    client_ip = get_client_ip(request)
    user_id = str(current_user.id)

    logger.info(
        "Logout all devices attempt started",
        extra={
            "event_type": "logout_all_attempt",
            "user_id": user_id,
            "client_ip": client_ip,
        },
    )

    try:
        # Get current session ID to potentially keep it active
        auth_header = request.headers.get("authorization")
        current_session_id = None

        if auth_header and auth_header.startswith("Bearer "):
            try:
                token = auth_header.split(" ")[1]
                payload = TokenManager.decode_token(token)
                current_session_id = payload.get("sid")
            except Exception:
                pass

        # Terminate all user sessions
        terminated_sessions = await SessionManager.terminate_all_user_sessions(
            db=db,
            user_id=current_user.id,
            except_session_id=current_session_id,  # Keep current session if identified
        )

        # Revoke all refresh tokens
        current_user.revoke_all_refresh_tokens()
        await db.commit()

        # Clear current cookie
        response.delete_cookie(
            key="refresh_token",
            httponly=True,
            secure=IS_PRODUCTION,
            samesite="none" if IS_PRODUCTION else "lax",
        )

        duration_ms = (time.time() - start_time) * 1000

        log_security_event(
            event_type="logout_all_success",
            details={
                "duration_ms": duration_ms,
                "all_refresh_tokens_revoked": True,
                "sessions_terminated": terminated_sessions,
                "current_session_preserved": bool(current_session_id),
            },
            user_id=user_id,
            ip_address=client_ip,
        )

        log_audit_event(
            action="logout_all_devices",
            resource_type="user_session",
            resource_id=user_id,
            user_id=user_id,
        )

        logger.info(
            "Logout all devices successful",
            extra={
                "event_type": "logout_all_success",
                "user_id": user_id,
                "sessions_terminated": terminated_sessions,
                "duration_ms": duration_ms,
            },
        )

        return {
            "data": {
                "message": "Logged out from all devices successfully",
                "sessions_terminated": terminated_sessions,
            }
        }

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Logout all devices failed due to unexpected error",
            extra={
                "event_type": "logout_all_error",
                "user_id": user_id,
                "error": str(e),
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )

        await db.rollback()

        raise HTTPException(status_code=500, detail="Logout from all devices failed")


# New endpoint for session management
@router.get("/sessions")
async def get_user_sessions(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Get all active sessions for current user"""
    try:
        from sqlalchemy import desc
        from app.models.user import UserSession

        result = await db.execute(
            select(UserSession)
            .where(UserSession.user_id == current_user.id)
            .where(UserSession.is_active == True)
            .order_by(desc(UserSession.last_activity))
        )

        sessions = result.scalars().all()

        session_data = []
        for session in sessions:
            session_data.append(
                {
                    "id": str(session.id),
                    "device_info": session.user_agent,
                    "ip_address": session.ip_address,
                    "location": (
                        f"{session.city}, {session.country}"
                        if session.city and session.country
                        else "Unknown"
                    ),
                    "created_at": session.created_at.isoformat(),
                    "last_activity": session.last_activity.isoformat(),
                    "is_current": False,  # Could be enhanced to detect current session
                    "login_method": session.login_method,
                    "risk_score": session.risk_score,
                }
            )

        return {"data": {"sessions": session_data}}

    except Exception as e:
        logger.error(
            "Failed to retrieve user sessions",
            extra={
                "event_type": "get_sessions_error",
                "user_id": str(current_user.id),
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve sessions")


@router.delete("/sessions/{session_id}")
async def terminate_user_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Terminate a specific session"""
    try:
        from uuid import UUID

        session_uuid = UUID(session_id)

        # Verify session belongs to current user
        result = await db.execute(
            select(UserSession).where(
                UserSession.id == session_uuid, UserSession.user_id == current_user.id
            )
        )

        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        success = await SessionManager.terminate_session(
            db=db, session_id=session_uuid, reason="user_terminated"
        )

        if success:
            return {"data": {"message": "Session terminated successfully"}}
        else:
            raise HTTPException(status_code=400, detail="Failed to terminate session")

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    except Exception as e:
        logger.error(
            "Failed to terminate session",
            extra={
                "event_type": "terminate_session_error",
                "user_id": str(current_user.id),
                "session_id": session_id,
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to terminate session")
