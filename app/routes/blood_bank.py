from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.blood_bank import BloodBankCreate, BloodBankResponse, BloodBankUpdate, BloodBankBase
from app.services.blood_bank import BloodBankService
from app.models.user import User
from app.utils.permission_checker import require_permission
from app.dependencies import get_db
from uuid import UUID
from typing import List
from app.models.blood_bank import BloodBank
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.utils.ip_address_finder import (
    get_client_ip, 
    get_user_agent
)
from app.utils.logging_config import (
    get_logger, 
    log_audit_event, 
    log_security_event, 
    log_function_call,
    log_performance_metric
)
import time

# Get logger for this module
logger = get_logger(__name__)

router = APIRouter(
    prefix="/blood-banks",
    tags=["blood banks"]
)


@router.post("/create", response_model=BloodBankResponse)
@log_function_call(include_args=False, level="INFO")
async def create_blood_bank(
    blood_bank_data: BloodBankBase,
    request: Request,
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(require_permission(
        "facility.manage", "laboratory.manage"
    ))):
    """Create blood bank with comprehensive logging"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    logger.info(
        "Blood bank creation started",
        extra={
            "event_type": "blood_bank_creation_attempt",
            "current_user_id": current_user_id,
            "blood_bank_name": blood_bank_data.blood_bank_name,
            "client_ip": client_ip,
            "user_agent": user_agent
        }
    )

    try:
        # Check if the user is a facility administrator
        if current_user.role != "facility_administrator":
            log_security_event(
                event_type="blood_bank_creation_denied",
                details={
                    "reason": "insufficient_role",
                    "user_role": current_user.role,
                    "required_role": "facility_administrator"
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood bank creation denied - insufficient role",
                extra={
                    "event_type": "blood_bank_creation_denied",
                    "current_user_id": current_user_id,
                    "user_role": current_user.role,
                    "reason": "insufficient_role"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Only facility administrators can create blood banks"
            )

        # Check if the user already manages any blood bank
        result = await db.execute(
            select(BloodBank).where(BloodBank.manager_id == current_user.id)
        )

        existing_blood_bank = result.scalar_one_or_none()
        if existing_blood_bank:
            log_security_event(
                event_type="blood_bank_creation_denied",
                details={
                    "reason": "already_managing_blood_bank",
                    "existing_blood_bank_id": str(existing_blood_bank.id),
                    "existing_blood_bank_name": existing_blood_bank.blood_bank_name
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood bank creation denied - user already manages a blood bank",
                extra={
                    "event_type": "blood_bank_creation_denied",
                    "current_user_id": current_user_id,
                    "existing_blood_bank_id": str(existing_blood_bank.id),
                    "reason": "already_managing_blood_bank"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You are already managing a blood bank"
            )

        # Get the facility this user manages
        from app.models.health_facility import Facility
        facility_result = await db.execute(
            select(Facility).where(Facility.facility_manager_id == current_user.id)
        )

        facility = facility_result.scalar_one_or_none()

        if not facility:
            log_security_event(
                event_type="blood_bank_creation_denied",
                details={
                    "reason": "no_facility_association",
                    "user_id": current_user_id
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood bank creation denied - no facility association",
                extra={
                    "event_type": "blood_bank_creation_denied",
                    "current_user_id": current_user_id,
                    "reason": "no_facility_association"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="You must be associated with a facility first"
            )

        # Set the facility_id in the blood bank data
        blood_bank_complete = BloodBankCreate(
            **blood_bank_data.model_dump(),
            facility_id=facility.id,
            manager_id=current_user.id
        )

        blood_bank_service = BloodBankService(db)
        new_blood_bank = await blood_bank_service.create_blood_bank(blood_bank_complete)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful creation
        log_security_event(
            event_type="blood_bank_created",
            details={
                "blood_bank_name": blood_bank_data.blood_bank_name,
                "blood_bank_id": str(new_blood_bank.id),
                "facility_id": str(facility.id),
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )

        log_audit_event(
            action="create",
            resource_type="blood_bank",
            resource_id=str(new_blood_bank.id),
            new_values={
                "name": blood_bank_data.blood_bank_name,
                "phone": blood_bank_data.phone,
                "email": blood_bank_data.email,
                "facility_id": str(facility.id),
                "manager_id": current_user_id
            },
            user_id=current_user_id
        )

        logger.info(
            "Blood bank creation successful",
            extra={
                "event_type": "blood_bank_created",
                "blood_bank_id": str(new_blood_bank.id),
                "current_user_id": current_user_id,
                "blood_bank_name": blood_bank_data.blood_bank_name,
                "facility_id": str(facility.id),
                "duration_ms": duration_ms
            }
        )

        # Log performance metric for slow operations
        if duration_ms > 2000:  # More than 2 seconds
            log_performance_metric(
                operation="blood_bank_creation",
                duration=duration_ms,
                additional_metrics={
                    "slow_operation": True,
                    "facility_association_check": True,
                    "license_validation": True
                }
            )

        return BloodBankResponse.model_validate(new_blood_bank, from_attributes=True)

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Blood bank creation failed due to unexpected error",
            extra={
                "event_type": "blood_bank_creation_error",
                "current_user_id": current_user_id,
                "blood_bank_name": blood_bank_data.blood_bank_name,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        log_security_event(
            event_type="blood_bank_creation_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "blood_bank_name": blood_bank_data.blood_bank_name,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )
        
        raise HTTPException(status_code=500, detail="Blood bank creation failed")


@router.get("/get-blood-bank/{blood_bank_id}", response_model=BloodBankResponse)
async def get_blood_bank_by_id(
    blood_bank_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get blood bank by ID with comprehensive logging"""
    start_time = time.time()
    client_ip = get_client_ip(request)
    target_blood_bank_id = str(blood_bank_id)

    logger.info(
        "Blood bank retrieval started",
        extra={
            "event_type": "blood_bank_retrieval_attempt",
            "blood_bank_id": target_blood_bank_id,
            "client_ip": client_ip
        }
    )

    try:
        # Eagerly load the relationships
        result = await db.execute(
            select(BloodBank)
            .options(selectinload(BloodBank.facility), selectinload(BloodBank.manager_user))
            .where(BloodBank.id == blood_bank_id)
        )

        blood_bank = result.scalar_one_or_none()

        if not blood_bank:
            log_security_event(
                event_type="blood_bank_access_denied",
                details={
                    "reason": "blood_bank_not_found",
                    "blood_bank_id": target_blood_bank_id
                },
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood bank retrieval failed - blood bank not found",
                extra={
                    "event_type": "blood_bank_retrieval_failed",
                    "blood_bank_id": target_blood_bank_id,
                    "reason": "blood_bank_not_found"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Blood bank not found"
            )

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "Blood bank retrieval successful",
            extra={
                "event_type": "blood_bank_retrieved",
                "blood_bank_id": target_blood_bank_id,
                "blood_bank_name": blood_bank.blood_bank_name,
                "facility_id": str(blood_bank.facility_id),
                "duration_ms": duration_ms
            }
        )

        # Log performance metric for slow queries
        if duration_ms > 500:  # More than 500ms
            log_performance_metric(
                operation="blood_bank_retrieval",
                duration=duration_ms,
                additional_metrics={
                    "slow_query": True,
                    "blood_bank_id": target_blood_bank_id,
                    "relationships_loaded": True
                }
            )

        return BloodBankResponse.model_validate(blood_bank, from_attributes=True)

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Blood bank retrieval failed due to unexpected error",
            extra={
                "event_type": "blood_bank_retrieval_error",
                "blood_bank_id": target_blood_bank_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve blood bank")


@router.get("/all", response_model=List[BloodBankResponse])
async def get_all_blood_banks(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get all blood banks with comprehensive logging"""
    start_time = time.time()
    client_ip = get_client_ip(request)

    logger.info(
        "All blood banks retrieval started",
        extra={
            "event_type": "all_blood_banks_retrieval_attempt",
            "client_ip": client_ip
        }
    )

    try:
        blood_bank_service = BloodBankService(db)
        blood_banks = await blood_bank_service.get_all_blood_banks()
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "All blood banks retrieval successful",
            extra={
                "event_type": "all_blood_banks_retrieved",
                "blood_banks_count": len(blood_banks),
                "duration_ms": duration_ms
            }
        )

        # Log performance metric for slow queries
        if duration_ms > 1000:  # More than 1 second
            log_performance_metric(
                operation="get_all_blood_banks",
                duration=duration_ms,
                additional_metrics={
                    "slow_query": True,
                    "result_count": len(blood_banks)
                }
            )

        return blood_banks

    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "All blood banks retrieval failed due to unexpected error",
            extra={
                "event_type": "all_blood_banks_retrieval_error",
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve blood banks")


@router.patch("/update/{blood_bank_id}", response_model=BloodBankResponse)
@log_function_call(include_args=False, level="INFO")
async def update_blood_bank(
    blood_bank_id: UUID, 
    blood_bank_data: BloodBankUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(require_permission(
        "facility.manage", "laboratory.manage"
    ))
):
    """Update blood bank with comprehensive logging"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    target_blood_bank_id = str(blood_bank_id)
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    logger.info(
        "Blood bank update started",
        extra={
            "event_type": "blood_bank_update_attempt",
            "blood_bank_id": target_blood_bank_id,
            "current_user_id": current_user_id,
            "client_ip": client_ip,
            "user_agent": user_agent,
            "update_fields": list(blood_bank_data.model_dump(exclude_unset=True).keys())
        }
    )

    try:
        blood_bank_service = BloodBankService(db)
        existing_blood_bank = await blood_bank_service.get_blood_bank(blood_bank_id)

        if not existing_blood_bank:
            log_security_event(
                event_type="blood_bank_update_denied",
                details={
                    "reason": "blood_bank_not_found",
                    "blood_bank_id": target_blood_bank_id
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood bank update failed - blood bank not found",
                extra={
                    "event_type": "blood_bank_update_failed",
                    "blood_bank_id": target_blood_bank_id,
                    "current_user_id": current_user_id,
                    "reason": "blood_bank_not_found"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Blood bank not found"
            )

        # Check if the current user is the manager of this blood bank
        if existing_blood_bank.manager_id != current_user.id:
            log_security_event(
                event_type="blood_bank_update_denied",
                details={
                    "reason": "insufficient_permissions",
                    "blood_bank_id": target_blood_bank_id,
                    "blood_bank_manager_id": str(existing_blood_bank.manager_id),
                    "requesting_user_id": current_user_id
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood bank update denied - insufficient permissions",
                extra={
                    "event_type": "blood_bank_update_denied",
                    "blood_bank_id": target_blood_bank_id,
                    "current_user_id": current_user_id,
                    "blood_bank_manager_id": str(existing_blood_bank.manager_id),
                    "reason": "insufficient_permissions"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="You do not have permission to update this blood bank"
            )

        # Store old values for audit trail
        old_values = {
            "name": existing_blood_bank.blood_bank_name,
            "phone": existing_blood_bank.phone,
            "email": existing_blood_bank.email
        }

        # Update blood bank
        updated_blood_bank = await blood_bank_service.update_blood_bank(blood_bank_id, blood_bank_data)
        
        # Store new values for audit
        new_values = {
            "name": updated_blood_bank.blood_bank_name,
            "phone": updated_blood_bank.phone,
            "email": updated_blood_bank.email
        }
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful update
        log_security_event(
            event_type="blood_bank_updated",
            details={
                "blood_bank_name": updated_blood_bank.blood_bank_name,
                "blood_bank_id": target_blood_bank_id,
                "duration_ms": duration_ms,
                "fields_updated": list(blood_bank_data.model_dump(exclude_unset=True).keys())
            },
            user_id=current_user_id,
            ip_address=client_ip
        )

        log_audit_event(
            action="update",
            resource_type="blood_bank",
            resource_id=target_blood_bank_id,
            old_values=old_values,
            new_values=new_values,
            user_id=current_user_id
        )

        logger.info(
            "Blood bank update successful",
            extra={
                "event_type": "blood_bank_updated",
                "blood_bank_id": target_blood_bank_id,
                "current_user_id": current_user_id,
                "blood_bank_name": updated_blood_bank.blood_bank_name,
                "duration_ms": duration_ms,
                "fields_updated": list(blood_bank_data.model_dump(exclude_unset=True).keys())
            }
        )

        # Log performance metric for slow operations
        if duration_ms > 1500:  # More than 1.5 seconds
            log_performance_metric(
                operation="blood_bank_update",
                duration=duration_ms,
                additional_metrics={
                    "slow_operation": True,
                    "blood_bank_id": target_blood_bank_id,
                    "update_fields_count": len(blood_bank_data.model_dump(exclude_unset=True))
                }
            )

        return BloodBankResponse.model_validate(updated_blood_bank, from_attributes=True)

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Blood bank update failed due to unexpected error",
            extra={
                "event_type": "blood_bank_update_error",
                "blood_bank_id": target_blood_bank_id,
                "current_user_id": current_user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        log_security_event(
            event_type="blood_bank_update_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "blood_bank_id": target_blood_bank_id,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )
        
        raise HTTPException(status_code=500, detail="Blood bank update failed")


@router.delete("/delete/{blood_bank_id}", status_code=status.HTTP_204_NO_CONTENT)
@log_function_call(include_args=False, level="INFO")
async def delete_blood_bank(
    blood_bank_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(require_permission(
        "facility.manage"
    ))):
    """Delete blood bank with comprehensive logging"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    target_blood_bank_id = str(blood_bank_id)
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    logger.info(
        "Blood bank deletion started",
        extra={
            "event_type": "blood_bank_deletion_attempt",
            "blood_bank_id": target_blood_bank_id,
            "current_user_id": current_user_id,
            "client_ip": client_ip,
            "user_agent": user_agent
        }
    )

    try:
        # Get the blood bank
        blood_bank_service = BloodBankService(db)
        blood_bank = await blood_bank_service.get_blood_bank(blood_bank_id)

        if not blood_bank:
            log_security_event(
                event_type="blood_bank_deletion_denied",
                details={
                    "reason": "blood_bank_not_found",
                    "blood_bank_id": target_blood_bank_id
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood bank deletion failed - blood bank not found",
                extra={
                    "event_type": "blood_bank_deletion_failed",
                    "blood_bank_id": target_blood_bank_id,
                    "current_user_id": current_user_id,
                    "reason": "blood_bank_not_found"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Blood bank not found"
            )

        # Check if the current user is the manager
        is_manager = blood_bank.manager_id == current_user.id
        is_facility_manager = blood_bank.facility.facility_manager_id == current_user.id if blood_bank.facility else False
        
        if not (is_manager or is_facility_manager):
            log_security_event(
                event_type="blood_bank_deletion_denied",
                details={
                    "reason": "insufficient_permissions",
                    "blood_bank_id": target_blood_bank_id,
                    "blood_bank_manager_id": str(blood_bank.manager_id),
                    "facility_manager_id": str(blood_bank.facility.facility_manager_id) if blood_bank.facility else None,
                    "requesting_user_id": current_user_id
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood bank deletion denied - insufficient permissions",
                extra={
                    "event_type": "blood_bank_deletion_denied",
                    "blood_bank_id": target_blood_bank_id,
                    "current_user_id": current_user_id,
                    "blood_bank_manager_id": str(blood_bank.manager_id),
                    "reason": "insufficient_permissions"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="You do not have permission to delete this blood bank"
            )

        # Store blood bank data for audit before deletion
        blood_bank_data_for_audit = {
            "name": blood_bank.blood_bank_name,
            "phone": blood_bank.phone,
            "email": blood_bank.email,
            "facility_id": str(blood_bank.facility_id),
            "manager_id": str(blood_bank.manager_id)
        }

        # Delete blood bank
        await blood_bank_service.delete_blood_bank(blood_bank_id)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful deletion
        log_security_event(
            event_type="blood_bank_deleted",
            details={
                "blood_bank_name": blood_bank.blood_bank_name,
                "facility_id": str(blood_bank.facility_id),
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )

        log_audit_event(
            action="delete",
            resource_type="blood_bank",
            resource_id=target_blood_bank_id,
            old_values=blood_bank_data_for_audit,
            new_values=None,
            user_id=current_user_id
        )

        logger.info(
            "Blood bank deletion successful",
            extra={
                "event_type": "blood_bank_deleted",
                "blood_bank_id": target_blood_bank_id,
                "current_user_id": current_user_id,
                "blood_bank_name": blood_bank.blood_bank_name,
                "duration_ms": duration_ms
            }
        )

        # Log performance metric for slow operations
        if duration_ms > 2000:  # More than 2 seconds
            log_performance_metric(
                operation="blood_bank_deletion",
                duration=duration_ms,
                additional_metrics={
                    "slow_operation": True,
                    "cascade_deletions_possible": True
                }
            )

        return {"detail": "Blood bank deleted successfully"}

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Blood bank deletion failed due to unexpected error",
            extra={
                "event_type": "blood_bank_deletion_error",
                "blood_bank_id": target_blood_bank_id,
                "current_user_id": current_user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        log_security_event(
            event_type="blood_bank_deletion_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "blood_bank_id": target_blood_bank_id,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )
        
        raise HTTPException(status_code=500, detail="Blood bank deletion failed")