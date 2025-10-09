import traceback
from app.utils.ip_address_finder import get_client_ip
from fastapi import (
    APIRouter, 
    Depends, 
    HTTPException, 
    status, 
    Response, 
    Request
)
from app.schemas.user_schema import (
    UserCreate, 
    UserResponse, 
    UserUpdate, 
    UserWithFacility
) 
from app.services.user_service import UserService
from app.dependencies import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user_model import User
from fastapi import BackgroundTasks
from app.utils.security import verify_token_and_extract_data
from sqlalchemy.future import select
from app.utils.data_wrapper import DataWrapper
from uuid import UUID
from app.utils.permission_checker import (
    require_permission
)
from app.utils import supervisor
from app.utils.logging_config import (
    get_logger, 
    log_security_event, 
    log_audit_event, 
    log_performance_metric
)
import time

# Get logger for this module
logger = get_logger(__name__)

router = APIRouter(
    prefix="/users",
    tags=["users"]
)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate, 
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Create a new user with comprehensive logging"""
    start_time = time.time()
    client_ip = get_client_ip(request)

    logger.info(
        "User registration started",
        extra={
            "event_type": "user_registration_attempt",
            "email": user_data.email,
            "role": user_data.role,
            "client_ip": client_ip
        }
    )

    try:
        # Validate role restrictions
        if user_data.role in ["lab_manager", "staff"]:
            log_security_event(
                event_type="registration_denied",
                details={
                    "reason": "requires admin",
                    "requested_role": user_data.role,
                    "email": user_data.email
                },
                ip_address=client_ip
            )

            logger.warning(
                "Registration denied - restricted role",
                extra={
                    "event_type": "registration_denied",
                    "email": user_data.email,
                    "requested_role": user_data.role,
                    "reason": "restricted_role"
                }
            )

            raise HTTPException(
                status_code=403, 
                detail=f"Cannot create account for {user_data.role}."
            )

        # Create user
        user_service = UserService(db)
        created_user = await user_service.create_user(user_data, background_tasks)
        await db.refresh(created_user, ["roles", "facility"])

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful registration
        log_security_event(
            event_type="user_registered",
            details={
                "email": user_data.email,
                "role": user_data.role,
                "user_id": str(created_user.id),
                "duration_ms": duration_ms,
                "verification_required": True
            },
            user_id=str(created_user.id),
            ip_address=client_ip
        )

        log_audit_event(
            action="create",
            resource_type="user",
            resource_id=str(created_user.id),
            new_values={
                "email": user_data.email,
                "last_name": user_data.last_name,
                "role": user_data.role,
                "is_verified": False
            },
            user_id=str(created_user.id)
        )

        logger.info(
            "User registration successful",
            extra={
                "event_type": "user_registered",
                "user_id": str(created_user.id),
                "email": user_data.email,
                "role": user_data.role,
                "duration_ms": duration_ms
            }
        )

        # Log performance metric for slow registrations
        if duration_ms > 2000:  # More than 2 seconds
            log_performance_metric(
                operation="user_registration",
                duration_seconds=duration_ms,
                additional_metrics={
                    "slow_operation": True,
                    "email_verification_sent": True
                }
            )

        return UserResponse.model_validate(created_user, from_attributes=True)

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "User registration failed due to unexpected error",
            extra={
                "event_type": "registration_error",
                "email": user_data.email,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        logger.error(
            f"User registration failed due to unexpected error: {str(e)}",
            extra={
                "event_type": "user_registration_failed",
                "email": getattr(user_data, "email", None),
                "client_ip": client_ip,
            },
        )
        log_security_event(
            event_type="registration_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "email": user_data.email,
                "duration_ms": duration_ms
            },
            ip_address=client_ip
        )

        raise HTTPException(status_code=500, detail="Registration failed")


@router.get("/verify-email")
async def verify_email(
    token: str, 
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Verify email"""
    start_time = time.time()
    client_ip = get_client_ip(request)
    
    logger.info(
        "Email verification started",
        extra={
            "event_type": "email_verification_attempt",
            "client_ip": client_ip,
            "token_present": bool(token)
        }
    )
    
    try:
        # Extract data from token
        token_data = verify_token_and_extract_data(token)
        email = token_data["email"]
        role = token_data["role"]
        facility_id = token_data.get("facility_id")

        if not email or not role:
            log_security_event(
                event_type="email_verification_failed",
                details={
                    "reason": "invalid_token_data",
                    "email": email,
                    "role": role
                },
                ip_address=client_ip
            )
            
            logger.warning(
                "Email verification failed - invalid token data",
                extra={
                    "event_type": "email_verification_failed",
                    "email": email,
                    "role": role,
                    "reason": "invalid_token_data"
                }
            )
            
            raise HTTPException(status_code=400, detail="Invalid token data")

        # Find user
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            log_security_event(
                event_type="email_verification_failed",
                details={
                    "reason": "user_not_found",
                    "email": email
                },
                ip_address=client_ip
            )
            
            logger.warning(
                "Email verification failed - user not found",
                extra={
                    "event_type": "email_verification_failed",
                    "email": email,
                    "reason": "user_not_found"
                }
            )
            
            raise HTTPException(status_code=400, detail="User not found")
        
        if user.is_verified:
            log_security_event(
                event_type="email_verification_failed",
                details={
                    "reason": "already_verified",
                    "email": email,
                    "user_id": str(user.id)
                },
                user_id=str(user.id),
                ip_address=client_ip
            )
            
            logger.warning(
                "Email verification failed - already verified",
                extra={
                    "event_type": "email_verification_failed",
                    "user_id": str(user.id),
                    "email": email,
                    "reason": "already_verified"
                }
            )
            
            raise HTTPException(status_code=400, detail="User already verified")

        # Verify token matches
        if user.verification_token != token:
            log_security_event(
                event_type="email_verification_failed",
                details={
                    "reason": "token_mismatch",
                    "email": email,
                    "user_id": str(user.id)
                },
                user_id=str(user.id),
                ip_address=client_ip
            )
            
            logger.warning(
                "Email verification failed - token mismatch",
                extra={
                    "event_type": "email_verification_failed",
                    "user_id": str(user.id),
                    "email": email,
                    "reason": "token_mismatch"
                }
            )
            
            raise HTTPException(status_code=400, detail="Invalid token")

        # Store old values for audit
        old_values = {
            "is_verified": user.is_verified,
            "verification_token": bool(user.verification_token)
        }

        # Mark as verified
        user.is_verified = True
        user.verification_token = None
        
        # Assign role
        await supervisor.assign_role(db, user_id=user.id, role_name=role)
        
        # Assign work facility if applicable
        if facility_id and role in ["staff", "lab_manager"]:
            user.work_facility_id = UUID(facility_id)
        
        await db.commit()
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Log successful verification
        log_security_event(
            event_type="email_verified",
            details={
                "email": email,
                "role_assigned": role,
                "facility_assigned": bool(facility_id),
                "duration_ms": duration_ms
            },
            user_id=str(user.id),
            ip_address=client_ip
        )
        
        log_audit_event(
            action="verify",
            resource_type="user",
            resource_id=str(user.id),
            old_values=old_values,
            new_values={
                "is_verified": True,
                "role": role,
                "work_facility_id": str(facility_id) if facility_id else None
            },
            user_id=str(user.id)
        )
        
        logger.info(
            "Email verification successful",
            extra={
                "event_type": "email_verified",
                "user_id": str(user.id),
                "email": email,
                "role_assigned": role,
                "duration_ms": duration_ms
            }
        )
        
        return {
            "message": "Email successfully verified!",
            "role_assigned": role
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Email verification failed due to unexpected error",
            extra={
                "event_type": "email_verification_error",
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        log_security_event(
            event_type="email_verification_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "duration_ms": duration_ms
            },
            ip_address=client_ip
        )
        
        raise HTTPException(status_code=500, detail="Email verification failed")


@router.get("/me", response_model=DataWrapper[UserWithFacility])
async def get_me(
    request: Request,
    current_user: User = Depends(require_permission(
        "can_view_profile",
        "facility.manage",
        "laboratory.manage",
    ))
):
    """Get current user profile"""
    start_time = time.time()
    user_id = str(current_user.id)
    
    logger.info(
        "Profile access",
        extra={
            "event_type": "profile_access",
            "user_id": user_id
        }
    )
    
    try:
        # Convert to Pydantic model
        user_data = UserWithFacility.model_validate(current_user, from_attributes=True)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "Profile access successful",
            extra={
                "event_type": "profile_access_success",
                "user_id": user_id,
                "duration_ms": duration_ms
            }
        )
        
        return {"data": user_data}
        
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Profile access failed due to unexpected error",
            extra={
                "event_type": "profile_access_error",
                "user_id": user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve profile")


@router.patch("/update-account/{user_id}", response_model=DataWrapper[UserResponse])
async def update_user(
        user_id: UUID,
        user_data: UserUpdate,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(
        require_permission(
                "staff.manage", 
                "facility.manage", 
                "laboratory.manage"
            )
        ),
    ):
    """Update user account"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    target_user_id = str(user_id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "User update started",
        extra={
            "event_type": "user_update_attempt",
            "target_user_id": target_user_id,
            "current_user_id": current_user_id,
            "client_ip": client_ip
        }
    )
    
    try:
        # Check permissions
        current_user_roles = [role.name for role in current_user.roles] if current_user.roles else []
        
        if (target_user_id != current_user_id and 
            not any(role in current_user_roles for role in ["facility_administrator", "lab_manager"])):
            
            log_security_event(
                event_type="user_update_denied",
                details={
                    "reason": "insufficient_permissions",
                    "target_user_id": target_user_id,
                    "current_user_roles": current_user_roles
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "User update denied - insufficient permissions",
                extra={
                    "event_type": "user_update_denied",
                    "target_user_id": target_user_id,
                    "current_user_id": current_user_id,
                    "reason": "insufficient_permissions"
                }
            )
            
            raise HTTPException(
                status_code=403, 
                detail="Require admin"
            )
        
        # Get original user data for audit trail
        user_service = UserService(db)
        original_user = await user_service.get_user(user_id)
        
        if not original_user:
            logger.warning(
                "User update failed - target user not found",
                extra={
                    "event_type": "user_update_failed",
                    "target_user_id": target_user_id,
                    "reason": "user_not_found"
                }
            )
            raise HTTPException(status_code=404, detail="User not found")
        
        # Store old values for audit
        old_values = {
            "last_name": original_user.last_name,
            "email": original_user.email,
            # Add other fields that might be updated
        }
        
        # Update user
        updated_user = await user_service.update_user(user_id, user_data)
        
        # Store new values for audit
        new_values = {
            "last_name": updated_user.last_name,
            "email": updated_user.email,
            # Add other fields that were updated
        }
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Log successful update
        log_audit_event(
            action="update",
            resource_type="user",
            resource_id=target_user_id,
            old_values=old_values,
            new_values=new_values,
            user_id=current_user_id
        )
        
        logger.info(
            "User update successful",
            extra={
                "event_type": "user_updated",
                "target_user_id": target_user_id,
                "current_user_id": current_user_id,
                "duration_ms": duration_ms,
                "fields_updated": list(user_data.model_dump(exclude_unset=True).keys())
            }
        )
        
        return {"data": updated_user}
        
    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "User update failed due to unexpected error",
            extra={
                "event_type": "user_update_error",
                "target_user_id": target_user_id,
                "current_user_id": current_user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="User update failed")


@router.delete("/delete-account/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
        user_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(require_permission(
        "staff.manage", "facility.manage", "laboratory.manage"
    )),
    ):
    """Delete user account with comprehensive logging"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    target_user_id = str(user_id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "User deletion started",
        extra={
            "event_type": "user_deletion_attempt",
            "target_user_id": target_user_id,
            "current_user_id": current_user_id,
            "client_ip": client_ip
        }
    )
    
    try:
        # Get user service and target user
        user_service = UserService(db)
        target_user = await user_service.get_user(user_id)

        if not target_user:
            logger.warning(
                "User deletion failed - target user not found",
                extra={
                    "event_type": "user_deletion_failed",
                    "target_user_id": target_user_id,
                    "reason": "user_not_found"
                }
            )
            raise HTTPException(status_code=404, detail="User not found")

        # Check facility permissions
        current_user_facility_id = current_user.work_facility_id or (
            current_user.facility.id if current_user.facility else None
        )

        if (
            target_user.work_facility_id and
            target_user.work_facility_id != current_user_facility_id
        ):
            log_security_event(
                event_type="user_deletion_denied",
                details={
                    "reason": "different_facility",
                    "target_user_id": target_user_id,
                    "target_facility": str(
                        target_user.work_facility_id if 
                        target_user.work_facility_id else 
                        target_user.facility.id
                    ),
                    "current_facility": str(current_user_facility_id)
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "User deletion denied - different facility",
                extra={
                    "event_type": "user_deletion_denied",
                    "target_user_id": target_user_id,
                    "current_user_id": current_user_id,
                    "reason": "different_facility"
                }
            )
            
            raise HTTPException(
                status_code=403, 
                detail="You can only delete users from your own facility"
            )

        # Store user data for audit before deletion
        user_data_for_audit = {
            "email": target_user.email,
            "last_name": target_user.last_name,
            "is_verified": target_user.is_verified,
            "work_facility_id": str(target_user.work_facility_id) if target_user.work_facility_id else None
        }

        # Delete user
        await user_service.delete_user(user_id)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Log successful deletion
        log_security_event(
            event_type="user_deleted",
            details={
                "target_user_email": target_user.email,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )
        
        log_audit_event(
            action="delete",
            resource_type="user",
            resource_id=target_user_id,
            old_values=user_data_for_audit,
            new_values=None,
            user_id=current_user_id
        )
        
        logger.info(
            "User deletion successful",
            extra={
                "event_type": "user_deleted",
                "target_user_id": target_user_id,
                "current_user_id": current_user_id,
                "target_email": target_user.email,
                "duration_ms": duration_ms
            }
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "User deletion failed due to unexpected error",
            extra={
                "event_type": "user_deletion_error",
                "target_user_id": target_user_id,
                "current_user_id": current_user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="User deletion failed")


@router.post("/staff/create", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_staff_user(
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "staff.manage", "facility.manage", "laboratory.manage"
    )),
):
    """Create staff user"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    client_ip = get_client_ip(request)

    logger.info(
        "Staff creation started",
        extra={
            "event_type": "staff_creation_attempt",
            "current_user_id": current_user_id,
            "target_email": user_data.email,
            "target_role": user_data.role,
            "client_ip": client_ip
        }
    )

    try:
        # Get current user roles
        current_user_roles = [role.name for role in current_user.roles] if current_user.roles else []

        # Validate role permissions
        if user_data.role == "lab_manager" and "lab_manager" in current_user_roles:
            log_security_event(
                event_type="staff_creation_denied",
                details={
                    "reason": "lab_manager_cannot_create_lab_manager",
                    "requested_role": user_data.role,
                    "current_user_roles": current_user_roles
                },
                user_id=current_user_id,
                ip_address=client_ip
            )

            logger.warning(
                "Staff creation denied - lab manager cannot create another lab manager",
                extra={
                    "event_type": "staff_creation_denied",
                    "current_user_id": current_user_id,
                    "requested_role": user_data.role,
                    "reason": "role_restriction"
                }
            )

            raise HTTPException(
                status_code=400, 
                detail="You can only assign staff to your lab."
            )

        # Check facility assignment
        if not current_user.facility:
            log_security_event(
                event_type="staff_creation_denied",
                details={
                    "reason": "no_facility_assigned",
                    "current_user_id": current_user_id
                },
                user_id=current_user_id,
                ip_address=client_ip
            )

            logger.warning(
                "Staff creation denied - no facility assigned",
                extra={
                    "event_type": "staff_creation_denied",
                    "current_user_id": current_user_id,
                    "reason": "no_facility_assigned"
                }
            )

            raise HTTPException(
                status_code=400, 
                detail="You are not assigned to any facility."
            )

        # Create user
        user_service = UserService(db)
        created_user = await user_service.create_user(
            user_data=user_data,
            background_tasks=background_tasks,
            work_facility_id=current_user.facility.id
        )

        # Refresh relationships
        await db.refresh(created_user, ["roles", "facility"])

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful creation
        log_security_event(
            event_type="staff_user_created",
            details={
                "target_email": user_data.email,
                "target_role": user_data.role,
                "facility_id": str(current_user.facility.id),
                "duration_ms": duration_ms,
                "verification_required": True
            },
            user_id=current_user_id,
            ip_address=client_ip
        )

        log_audit_event(
            action="create",
            resource_type="staff_user",
            resource_id=str(created_user.id),
            new_values={
                "email": user_data.email,
                "last_name": user_data.last_name,
                "role": user_data.role,
                "work_facility_id": str(current_user.facility.id),
                "created_by": current_user_id
            },
            user_id=current_user_id
        )

        logger.info(
            "Staff creation successful",
            extra={
                "event_type": "staff_user_created",
                "created_user_id": str(created_user.id),
                "current_user_id": current_user_id,
                "target_email": user_data.email,
                "target_role": user_data.role,
                "facility_id": str(current_user.facility.id),
                "duration_ms": duration_ms
            }
        )

        # Log performance metric for slow operations
        if duration_ms > 3000:  # More than 3 seconds
            log_performance_metric(
                operation="staff_user_creation",
                duration_seconds=duration_ms,
                additional_metrics={
                    "slow_operation": True,
                    "email_verification_sent": True,
                    "facility_assignment": True,
                },
            )

        return UserResponse.model_validate(created_user, from_attributes=True)

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Staff creation failed due to unexpected error",
            extra={
                "event_type": "staff_creation_error",
                "current_user_id": current_user_id,
                "target_email": user_data.email,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )

        log_security_event(
            event_type="staff_creation_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "target_email": user_data.email,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )

        raise HTTPException(status_code=500, detail="Staff creation failed")


@router.get("/staff", response_model=list[UserResponse])
async def get_all_staff_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "laboratory.manage", "facility.manage"
    ))
):
    """Get all staff users"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    
    logger.info(
        "Staff list access",
        extra={
            "event_type": "staff_list_access",
            "current_user_id": current_user_id,
            "facility_id": str(current_user.facility.id) if current_user.facility else None
        }
    )
    
    try:
        user_service = UserService(db)
        staff_users = await user_service.get_all_staff_users(current_user.facility.id)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "Staff list access successful",
            extra={
                "event_type": "staff_list_accessed",
                "current_user_id": current_user_id,
                "facility_id": str(current_user.facility.id),
                "staff_count": len(staff_users),
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow queries
        if duration_ms > 500:  # More than 500ms
            log_performance_metric(
                operation="get_staff_users",
                duration_seconds=duration_ms,
                additional_metrics={
                    "slow_query": True,
                    "result_count": len(staff_users),
                    "facility_id": str(current_user.facility.id)
                }
            )

        return staff_users
        
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Staff list access failed due to unexpected error",
            extra={
                "event_type": "staff_list_error",
                "current_user_id": current_user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve staff users")
