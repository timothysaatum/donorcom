from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.facility_schema import (
    FacilityBase, 
    FacilityResponse, 
    FacilityUpdate,
    FacilityWithBloodBankCreate,
    FacilityWithBloodBank
)
from app.services.facility_service import FacilityService
from app.models.user_model import User
from app.utils.permission_checker import require_permission
from app.dependencies import get_db
from uuid import UUID
from typing import List, Union
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
    prefix="/facilities",
    tags=["facilities"]
)


@router.post("/create", response_model=FacilityResponse)
@log_function_call(include_args=False, level="INFO")
async def create_facility(
    facility_data: FacilityBase,
    request: Request,
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(require_permission(
        "facility.manage"
    ))):
    """
        1. Create facility: A facility can only be added by the facility administrator
        2. A facility represents an entity that can request or issue blood to another facility
        3. It has to be physically located and posses officially recognized licenses from the appropriate regulating bodies
    
    """
    start_time = time.time()
    current_user_id = str(current_user.id)
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    logger.info(
        "Facility creation started",
        extra={
            "event_type": "facility_creation_attempt",
            "current_user_id": current_user_id,
            "facility_name": facility_data.facility_name,
            "client_ip": client_ip,
            "user_agent": user_agent
        }
    )

    try:
        facility_service = FacilityService(db)
        new_facility = await facility_service.create_facility(
            facility_data=facility_data,
            facility_manager_id=current_user.id
        )
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful creation
        log_security_event(
            event_type="facility_created",
            details={
                "facility_name": facility_data.facility_name,
                "facility_id": str(new_facility.id),
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )

        log_audit_event(
            action="create",
            resource_type="facility",
            resource_id=str(new_facility.id),
            new_values={
                "name": facility_data.facility_name,
                "address": facility_data.facility_digital_address,
                "facility_manager_id": current_user_id,
                "phone": facility_data.facility_contact_number,
                "email": facility_data.facility_email
            },
            user_id=current_user_id
        )

        logger.info(
            "Facility creation successful",
            extra={
                "event_type": "facility_created",
                "facility_id": str(new_facility.id),
                "current_user_id": current_user_id,
                "facility_name": facility_data.facility_name,
                "duration_ms": duration_ms
            }
        )

        # Log performance metric for slow operations
        if duration_ms > 2000:  # More than 2 seconds
            log_performance_metric(
                operation="facility_creation",
                duration=duration_ms,
                additional_metrics={
                    "slow_operation": True,
                    "facility": facility_data.facility_name
                }
            )

        return FacilityResponse.model_validate(new_facility, from_attributes=True)

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Facility creation failed due to unexpected error",
            extra={
                "event_type": "facility_creation_error",
                "current_user_id": current_user_id,
                "facility_name": facility_data.facility_name,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        log_security_event(
            event_type="facility_creation_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "facility_name": facility_data.facility_name,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )
        
        raise HTTPException(status_code=500, detail="Facility creation failed")


@router.post(
    "/create-with-blood-bank", 
    response_model=Union[FacilityResponse, FacilityWithBloodBank]
)
@log_function_call(include_args=False, level="INFO")
async def create_facility_with_blood_bank(
    facility_data: FacilityWithBloodBankCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("facility.manage")),
):
    """Create facility with blood bank"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    logger.info(
        "Facility with blood bank creation started",
        extra={
            "event_type": "facility_with_blood_bank_creation_attempt",
            "current_user_id": current_user_id,
            "facility_name": facility_data.facility_name,
            "blood_bank_requested": bool(facility_data.blood_bank),
            "client_ip": client_ip,
            "user_agent": user_agent,
        },
    )

    try:
        facility_service = FacilityService(db)
        result = await facility_service.create_facility_with_blood_bank(
            facility_data=facility_data, facility_manager_id=current_user.id
        )

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Determine if blood bank was created
        blood_bank_created = hasattr(result, 'blood_bank') and result.blood_bank is not None

        # Log successful creation
        log_security_event(
            event_type="facility_with_blood_bank_created",
            details={
                "facility_name": facility_data.facility_name,
                "facility_id": str(result.id),
                "blood_bank_created": blood_bank_created,
                "duration_ms": duration_ms,
            },
            user_id=current_user_id,
            ip_address=client_ip,
        )

        # Prepare audit values
        new_values = {
            "facility_name": facility_data.facility_name,
            "facility_address": facility_data.facility_digital_address,
            "facility_manager_id": current_user_id,
            "facility_phone": facility_data.facility_contact_number,
            "facility_email": facility_data.facility_email,
            "blood_bank_created": blood_bank_created,
        }

        if blood_bank_created and facility_data.blood_bank:
            new_values.update({"blood_bank_name": facility_data.blood_bank})

        log_audit_event(
            action="create",
            resource_type="facility_with_blood_bank",
            resource_id=str(result.id),
            new_values=new_values,
            user_id=current_user_id
        )

        logger.info(
            "Facility with blood bank creation successful",
            extra={
                "event_type": "facility_with_blood_bank_created",
                "facility_id": str(result.id),
                "current_user_id": current_user_id,
                "facility_name": facility_data.facility_name,
                "blood_bank_created": blood_bank_created,
                "duration_ms": duration_ms,
            },
        )

        # Log performance metric for slow operations
        if duration_ms > 3000:  # More than 3 seconds
            log_performance_metric(
                operation="facility_with_blood_bank_creation",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_operation": True,
                    "blood_bank_included": blood_bank_created,
                    "facility_type": facility_data.facility_name,
                },
            )

        return result

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Facility with blood bank creation failed due to unexpected error",
            extra={
                "event_type": "facility_with_blood_bank_creation_error",
                "current_user_id": current_user_id,
                "facility_name": facility_data.facility_name,
                "error": str(e),
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )

        log_security_event(
            event_type="facility_with_blood_bank_creation_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "facility_name": facility_data.facility_name,
                "duration_ms": duration_ms,
            },
            user_id=current_user_id,
            ip_address=client_ip,
        )

        raise HTTPException(status_code=500, detail="Facility creation failed")


@router.get("/get-facility-by-id/{facility_id}", response_model=FacilityResponse)
async def get_facility_by_id(
    facility_id: UUID, 
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get facility by ID with comprehensive logging"""
    start_time = time.time()
    client_ip = get_client_ip(request)
    target_facility_id = str(facility_id)

    logger.info(
        "Facility retrieval started",
        extra={
            "event_type": "facility_retrieval_attempt",
            "facility_id": target_facility_id,
            "client_ip": client_ip
        }
    )

    try:
       
        facility_service = FacilityService(db)

        facility = await facility_service.get_facility(facility_id)

        if not facility:
            log_security_event(
                event_type="facility_access_denied",
                details={
                    "reason": "facility_not_found",
                    "facility_id": target_facility_id
                },
                ip_address=client_ip
            )
            
            logger.warning(
                "Facility retrieval failed - facility not found",
                extra={
                    "event_type": "facility_retrieval_failed",
                    "facility_id": target_facility_id,
                    "reason": "facility_not_found"
                }
            )
            
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facility not found")

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "Facility retrieval successful",
            extra={
                "event_type": "facility_retrieved",
                "facility_id": target_facility_id,
                "facility_name": facility.facility_name,
                "duration_ms": duration_ms
            }
        )

        # Log performance metric for slow queries
        if duration_ms > 500:  # More than 500ms
            log_performance_metric(
                operation="facility_retrieval",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_query": True,
                    "facility_id": target_facility_id
                }
            )

        return FacilityResponse.model_validate(facility, from_attributes=True)

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Facility retrieval failed due to unexpected error",
            extra={
                "event_type": "facility_retrieval_error",
                "facility_id": target_facility_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve facility")


@router.get("/all", response_model=List[FacilityResponse])
async def get_all_facilities(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get all facilities with comprehensive logging"""
    start_time = time.time()
    client_ip = get_client_ip(request)

    logger.info(
        "All facilities retrieval started",
        extra={
            "event_type": "all_facilities_retrieval_attempt",
            "client_ip": client_ip
        }
    )

    try:
        facility_service = FacilityService(db)
        facilities = await facility_service.get_all_facilities()
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "All facilities retrieval successful",
            extra={
                "event_type": "all_facilities_retrieved",
                "facilities_count": len(facilities),
                "duration_ms": duration_ms
            }
        )

        # Log performance metric for slow queries
        if duration_ms > 1000:  # More than 1 second
            log_performance_metric(
                operation="get_all_facilities",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_query": True,
                    "result_count": len(facilities)
                }
            )

        return facilities

    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "All facilities retrieval failed due to unexpected error",
            extra={
                "event_type": "all_facilities_retrieval_error",
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve facilities")


@router.patch("/update-facility/{facility_id}", response_model=FacilityResponse)
@log_function_call(include_args=False, level="INFO")
async def update_facility(
    facility_id: UUID, 
    facility_data: FacilityUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(require_permission(
        "facility.manage", "laboratory.manage"
    ))
):
    """Update facility with comprehensive logging"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    target_facility_id = str(facility_id)
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    logger.info(
        "Facility update started",
        extra={
            "event_type": "facility_update_attempt",
            "facility_id": target_facility_id,
            "current_user_id": current_user_id,
            "client_ip": client_ip,
            "user_agent": user_agent,
            "update_fields": list(facility_data.model_dump(exclude_unset=True).keys())
        }
    )

    try:
        facility_service = FacilityService(db)
        existing_facility = await facility_service.get_facility(facility_id)

        if not existing_facility:
            log_security_event(
                event_type="facility_update_denied",
                details={
                    "reason": "facility_not_found",
                    "facility_id": target_facility_id
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Facility update failed - facility not found",
                extra={
                    "event_type": "facility_update_failed",
                    "facility_id": target_facility_id,
                    "current_user_id": current_user_id,
                    "reason": "facility_not_found"
                }
            )
            
            raise HTTPException(status_code=404, detail="Facility not found")

        # Check permissions
        if existing_facility.facility_manager_id != current_user.id:
            log_security_event(
                event_type="facility_update_denied",
                details={
                    "reason": "insufficient_permissions",
                    "facility_id": target_facility_id,
                    "facility_manager_id": str(existing_facility.facility_manager_id),
                    "requesting_user_id": current_user_id
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Facility update denied - insufficient permissions",
                extra={
                    "event_type": "facility_update_denied",
                    "facility_id": target_facility_id,
                    "current_user_id": current_user_id,
                    "reason": "insufficient_permissions"
                }
            )
            
            raise HTTPException(status_code=403, detail="Permission denied")

        # Store old values for audit trail
        old_values = {
            "name": existing_facility.facility_name,
            "phone": existing_facility.facility_contact_number,
            "email": existing_facility.facility_email
        }

        # Update facility
        updated_facility = await facility_service.update_facility(facility_id, facility_data)
        
        # Store new values for audit
        new_values = {
            "name": updated_facility.facility_name,
            "address": updated_facility.facility_digital_address,
            "phone": updated_facility.facility_contact_number,
            "email": updated_facility.facility_email
        }
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful update
        log_security_event(
            event_type="facility_updated",
            details={
                "facility_name": updated_facility.facility_name,
                "facility_id": target_facility_id,
                "duration_ms": duration_ms,
                "fields_updated": list(facility_data.model_dump(exclude_unset=True).keys())
            },
            user_id=current_user_id,
            ip_address=client_ip
        )

        log_audit_event(
            action="update",
            resource_type="facility",
            resource_id=target_facility_id,
            old_values=old_values,
            new_values=new_values,
            user_id=current_user_id
        )

        logger.info(
            "Facility update successful",
            extra={
                "event_type": "facility_updated",
                "facility_id": target_facility_id,
                "current_user_id": current_user_id,
                "facility_name": updated_facility.facility_name,
                "duration_ms": duration_ms,
                "fields_updated": list(facility_data.model_dump(exclude_unset=True).keys())
            }
        )

        # Log performance metric for slow operations
        if duration_ms > 1500:  # More than 1.5 seconds
            log_performance_metric(
                operation="facility_update",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_operation": True,
                    "facility_id": target_facility_id,
                    "update_fields_count": len(facility_data.model_dump(exclude_unset=True))
                }
            )

        return updated_facility

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Facility update failed due to unexpected error",
            extra={
                "event_type": "facility_update_error",
                "facility_id": target_facility_id,
                "current_user_id": current_user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        log_security_event(
            event_type="facility_update_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "facility_id": target_facility_id,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )
        
        raise HTTPException(status_code=500, detail="Facility update failed")


@router.delete("/delete-facility/{facility_id}", status_code=status.HTTP_204_NO_CONTENT)
@log_function_call(include_args=False, level="INFO")
async def delete_facility(
    facility_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(require_permission(
        "facility.manage"
    ))
):
    """Delete facility with comprehensive logging"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    target_facility_id = str(facility_id)
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    logger.info(
        "Facility deletion started",
        extra={
            "event_type": "facility_deletion_attempt",
            "facility_id": target_facility_id,
            "current_user_id": current_user_id,
            "client_ip": client_ip,
            "user_agent": user_agent
        }
    )

    try:
        # Ensure the user is the facility manager for this facility
        facility_service = FacilityService(db)
        facility = await facility_service.get_facility(facility_id)

        if not facility:
            log_security_event(
                event_type="facility_deletion_denied",
                details={
                    "reason": "facility_not_found",
                    "facility_id": target_facility_id
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Facility deletion failed - facility not found",
                extra={
                    "event_type": "facility_deletion_failed",
                    "facility_id": target_facility_id,
                    "current_user_id": current_user_id,
                    "reason": "facility_not_found"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Facility not found"
            )

        # Check permissions
        if facility.facility_manager_id != current_user.id:
            log_security_event(
                event_type="facility_deletion_denied",
                details={
                    "reason": "insufficient_permissions",
                    "facility_id": target_facility_id,
                    "facility_manager_id": str(facility.facility_manager_id),
                    "requesting_user_id": current_user_id
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Facility deletion denied - insufficient permissions",
                extra={
                    "event_type": "facility_deletion_denied",
                    "facility_id": target_facility_id,
                    "current_user_id": current_user_id,
                    "facility_manager_id": str(facility.facility_manager_id),
                    "reason": "insufficient_permissions"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="You do not have permission to delete this facility"
            )

        # Store facility data for audit before deletion
        facility_data_for_audit = {
            "name": facility.facility_name,
            "address": facility.facility_digital_address,
            "phone": facility.facility_contact_number,
            "email": facility.facility_email,
            "facility_manager_id": str(facility.facility_manager_id)
        }

        # Delete facility
        await facility_service.delete_facility(facility_id)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful deletion
        log_security_event(
            event_type="facility_deleted",
            details={
                "facility_name": facility.facility_name,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )

        log_audit_event(
            action="delete",
            resource_type="facility",
            resource_id=target_facility_id,
            old_values=facility_data_for_audit,
            new_values=None,
            user_id=current_user_id
        )

        logger.info(
            "Facility deletion successful",
            extra={
                "event_type": "facility_deleted",
                "facility_id": target_facility_id,
                "current_user_id": current_user_id,
                "facility_name": facility.facility_name,
                "duration_ms": duration_ms
            }
        )

        # Log performance metric for slow operations
        if duration_ms > 2000:  # More than 2 seconds
            log_performance_metric(
                operation="facility_deletion",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_operation": True,
                    "facility_id": target_facility_id
                }
            )
        
        return {"detail": "Facility deleted successfully"}

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Facility deletion failed due to unexpected error",
            extra={
                "event_type": "facility_deletion_error",
                "facility_id": target_facility_id,
                "current_user_id": current_user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        log_security_event(
            event_type="facility_deletion_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "facility_id": target_facility_id,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )
        
        raise HTTPException(status_code=500, detail="Facility deletion failed")
