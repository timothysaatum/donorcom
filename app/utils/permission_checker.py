import uuid
from fastapi import Depends, HTTPException, status, Request
from app.models.user_model import User
from app.utils.security import (
    get_current_user,
    SessionManager,
    TokenManager,
)
from app.dependencies import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.logging_config import get_logger, log_security_event

logger = get_logger(__name__)


def require_permission(*perms: str, validate_session: bool = True):
    """
    Enhanced dependency factory to enforce permissions with optional session validation.

    Args:
        *perms: Required permissions (user needs at least one)
        validate_session: Whether to validate the user's session (default: True)

    Usage:
        current_user: User = Depends(require_permission("perm1", "perm2"))
        current_user: User = Depends(require_permission("admin", validate_session=False))
    """

    async def checker(
        current_user: User = Depends(get_current_user),
        request: Request = None,
        db: AsyncSession = Depends(get_db),
    ):
        # Enhanced logging
        logger.debug(
            "Permission check initiated",
            extra={
                "event_type": "permission_check_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "required_permissions": list(perms),
                "validate_session": validate_session,
            },
        )

        # Get user's actual permissions
        user_permissions = [
            perm.name for role in current_user.roles for perm in role.permissions
        ]

        logger.debug(
            "User permissions retrieved",
            extra={
                "event_type": "user_permissions_retrieved",
                "user_id": str(current_user.id),
                "user_permissions": user_permissions,
            },
        )

        # Check if user has any of the required permissions
        has_permission = any(current_user.has_permission(perm) for perm in perms)

        if not has_permission:
            # Log security event for unauthorized access attempt
            log_security_event(
                event_type="unauthorized_access_attempt",
                user_id=str(current_user.id),
                ip_address=(
                    getattr(request.client, "host", "unknown")
                    if request and request.client
                    else "unknown"
                ),
                user_agent=(
                    request.headers.get("user-agent", "unknown")
                    if request
                    else "unknown"
                ),
                details={
                    "required_permissions": list(perms),
                    "user_permissions": user_permissions,
                    "user_email": current_user.email,
                },
            )

            logger.warning(
                "Access denied - insufficient permissions",
                extra={
                    "event_type": "access_denied_permissions",
                    "user_id": str(current_user.id),
                    "required_permissions": list(perms),
                    "user_permissions": user_permissions,
                },
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires at least one of these permissions: {', '.join(perms)}",
            )

        # Optional session validation for high-security operations
        if validate_session and request:
            session_valid = await validate_user_session(
                db=db, current_user=current_user, request=request
            )

            if not session_valid:
                log_security_event(
                    event_type="invalid_session_access_attempt",
                    user_id=str(current_user.id),
                    ip_address=(
                        getattr(request.client, "host", "unknown")
                        if request.client
                        else "unknown"
                    ),
                    details={
                        "required_permissions": list(perms),
                        "session_validation_failed": True,
                    },
                )

                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session validation failed. Please login again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        logger.info(
            "Access granted - permission check passed",
            extra={
                "event_type": "access_granted",
                "user_id": str(current_user.id),
                "granted_permissions": [
                    perm for perm in perms if current_user.has_permission(perm)
                ],
                "session_validated": validate_session,
            },
        )

        return current_user

    return checker


def require_role(*roles: str, validate_session: bool = True):
    """
    Enhanced dependency factory to enforce roles with optional session validation.

    Args:
        *roles: Required roles (user needs at least one)
        validate_session: Whether to validate the user's session (default: True)

    Usage:
        current_user: User = Depends(require_role("admin", "manager"))
        current_user: User = Depends(require_role("staff", validate_session=False))
    """

    async def checker(
        current_user: User = Depends(get_current_user),
        request: Request = None,
        db: AsyncSession = Depends(get_db),
    ):
        logger.debug(
            "Role check initiated",
            extra={
                "event_type": "role_check_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "required_roles": list(roles),
                "validate_session": validate_session,
            },
        )

        # Get user's actual roles
        user_roles = [role.name for role in current_user.roles]

        logger.debug(
            "User roles retrieved",
            extra={
                "event_type": "user_roles_retrieved",
                "user_id": str(current_user.id),
                "user_roles": user_roles,
            },
        )

        # Check if user has any of the required roles
        has_role = any(current_user.has_role(role) for role in roles)

        if not has_role:
            # Log security event for unauthorized access attempt
            log_security_event(
                event_type="unauthorized_role_access_attempt",
                user_id=str(current_user.id),
                ip_address=(
                    getattr(request.client, "host", "unknown")
                    if request and request.client
                    else "unknown"
                ),
                user_agent=(
                    request.headers.get("user-agent", "unknown")
                    if request
                    else "unknown"
                ),
                details={
                    "required_roles": list(roles),
                    "user_roles": user_roles,
                    "user_email": current_user.email,
                },
            )

            logger.warning(
                "Access denied - insufficient roles",
                extra={
                    "event_type": "access_denied_roles",
                    "user_id": str(current_user.id),
                    "required_roles": list(roles),
                    "user_roles": user_roles,
                },
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires at least one of these roles: {', '.join(roles)}",
            )

        # Optional session validation for high-security operations
        if validate_session and request:
            session_valid = await validate_user_session(
                db=db, current_user=current_user, request=request
            )

            if not session_valid:
                log_security_event(
                    event_type="invalid_session_access_attempt",
                    user_id=str(current_user.id),
                    ip_address=(
                        getattr(request.client, "host", "unknown")
                        if request.client
                        else "unknown"
                    ),
                    details={
                        "required_roles": list(roles),
                        "session_validation_failed": True,
                    },
                )

                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session validation failed. Please login again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        logger.info(
            "Access granted - role check passed",
            extra={
                "event_type": "access_granted_role",
                "user_id": str(current_user.id),
                "granted_roles": [
                    role for role in roles if current_user.has_role(role)
                ],
                "session_validated": validate_session,
            },
        )

        return current_user

    return checker


async def validate_user_session(
    db: AsyncSession, current_user: User, request: Request
) -> bool:
    """
    Validate user session for high-security operations.

    Args:
        db: Database session
        current_user: Current authenticated user
        request: FastAPI request object

    Returns:
        bool: True if session is valid, False otherwise
    """
    try:
        # Extract session information from request

        authorization_header = request.headers.get("authorization")
        if not authorization_header or not authorization_header.startswith("Bearer "):
            logger.warning(
                "Session validation failed - missing or invalid authorization header",
                extra={
                    "event_type": "session_validation_failed",
                    "user_id": str(current_user.id),
                    "reason": "missing_auth_header",
                },
            )
            return False
        token = authorization_header.split(" ")[1]

        payload = TokenManager.decode_token(token)

        if not payload:
            logger.warning(
                "Session validation failed - invalid token",
                extra={
                    "event_type": "session_validation_failed",
                    "user_id": str(current_user.id),
                    "reason": "invalid_token",
                },
            )
            return False

        # Use SessionManager to validate the session
        session_manager = SessionManager()
        session_uuid = uuid.UUID(payload.get("sid"))
        is_valid = await session_manager.validate_session(
            db=db, session_id=session_uuid, request=request
        )

        if not is_valid:
            logger.warning(
                "Session validation failed - session not found or expired",
                extra={
                    "event_type": "session_validation_failed",
                    "user_id": str(current_user.id),
                    "reason": "invalid_session",
                },
            )
            return False

        logger.debug(
            "Session validation successful",
            extra={
                "event_type": "session_validation_success",
                "user_id": str(current_user.id),
            },
        )

        return True

    except Exception as e:
        logger.error(
            "Session validation error",
            extra={
                "event_type": "session_validation_error",
                "user_id": str(current_user.id),
                "error": str(e),
            },
        )
        return False


def require_admin(validate_session: bool = True):
    """
    Convenience function for requiring admin role.

    Args:
        validate_session: Whether to validate the user's session (default: True)

    Usage:
        current_user: User = Depends(require_admin())
        current_user: User = Depends(require_admin(validate_session=False))
    """
    return require_role("facility_administrator", validate_session=validate_session)


def require_sys_admin(role: str):

    pass


def require_staff(validate_session: bool = True):
    """
    Convenience function for requiring staff-level access (admin or staff roles).

    Args:
        validate_session: Whether to validate the user's session (default: True)

    Usage:
        current_user: User = Depends(require_staff())
        current_user: User = Depends(require_staff(validate_session=False))
    """
    return require_role(
        "facility_administrator",
        "lab_manager",
        "staff",
        validate_session=validate_session,
    )


def require_authenticated(validate_session: bool = False):
    """
    Basic authentication requirement without specific permissions or roles.

    Args:
        validate_session: Whether to validate the user's session (default: False)

    Usage:
        current_user: User = Depends(require_authenticated())
        current_user: User = Depends(require_authenticated(validate_session=True))
    """

    async def checker(
        current_user: User = Depends(get_current_user),
        request: Request = None,
        db: AsyncSession = Depends(get_db),
    ):
        logger.debug(
            "Authentication check initiated",
            extra={
                "event_type": "auth_check_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "validate_session": validate_session,
            },
        )

        # Optional session validation
        if validate_session and request:
            session_valid = await validate_user_session(
                db=db, current_user=current_user, request=request
            )

            if not session_valid:
                log_security_event(
                    event_type="invalid_session_auth_attempt",
                    user_id=str(current_user.id),
                    ip_address=(
                        getattr(request.client, "host", "unknown")
                        if request.client
                        else "unknown"
                    ),
                    details={"session_validation_failed": True},
                )

                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session validation failed. Please login again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        logger.debug(
            "Authentication check passed",
            extra={
                "event_type": "auth_check_passed",
                "user_id": str(current_user.id),
                "session_validated": validate_session,
            },
        )

        return current_user

    return checker
