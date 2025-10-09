import time
from app.utils.generic_id import get_user_blood_bank_id
from app.utils.ip_address_finder import get_client_ip
from app.utils.logging_config import log_audit_event, log_performance_metric, log_security_event
from fastapi import (
    APIRouter, 
    Depends, 
    HTTPException, 
    status, 
    Path, 
    Query, 
    BackgroundTasks
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.inventory_schema import (
    BloodInventoryCreate, 
    BloodInventoryResponse, 
    BloodInventoryUpdate, 
    BloodInventoryDetailResponse, 
    BloodInventoryBatchCreate, 
    BloodInventoryBatchUpdate,
    BloodInventoryBatchDelete, 
    BatchOperationResponse, 
    InventoryStatistics,
    BloodInventorySearchParams,
    PaginatedFacilityResponse
)
from app.services.inventory_service import BloodInventoryService
from app.models.user_model import User
from app.models.inventory_model import BloodInventory
from app.utils.pagination import PaginatedResponse, PaginationParams, get_pagination_params
from app.utils.security import get_current_user
from app.dependencies import get_db
from uuid import UUID
from typing import Optional, Annotated
from sqlalchemy.future import select
from datetime import datetime
import logging
from fastapi import Request
from app.utils.permission_checker import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/blood-inventory",
    tags=["blood inventory"]
)


@router.post("/", response_model=BloodInventoryResponse, status_code=status.HTTP_201_CREATED)
async def create_blood_unit(
    blood_data: BloodInventoryCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "inventory.manage", 
        "blood.inventory.manage"
        ))
    ):
    """
    Add a new blood unit to inventory.
    The blood bank and user who added it are automatically assigned.
    """
    start_time = time.time()
    user_id = str(current_user.id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "Blood unit creation started",
        extra={
            "event_type": "blood_unit_creation_attempt",
            "user_id": user_id,
            "blood_type": blood_data.blood_type,
            "blood_product": blood_data.blood_product,
            "quantity": blood_data.quantity,
            "client_ip": client_ip
        }
    )
    
    try:
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
        
        if not blood_bank_id:
            log_security_event(
                event_type="blood_unit_creation_denied",
                details={
                    "reason": "no_blood_bank_access",
                    "user_id": user_id
                },
                user_id=user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood unit creation denied - no blood bank access",
                extra={
                    "event_type": "blood_unit_creation_denied",
                    "user_id": user_id,
                    "reason": "no_blood_bank_access"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not belong to any facility or blood bank. Please contact admin."
            )
        
        blood_service = BloodInventoryService(db)
        new_blood_unit = await blood_service.create_blood_unit(
            blood_data=blood_data,
            blood_bank_id=blood_bank_id,
            added_by_id=current_user.id
        )
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Log successful creation
        log_security_event(
            event_type="blood_unit_created",
            details={
                "blood_unit_id": str(new_blood_unit.id),
                "blood_type": blood_data.blood_type,
                "blood_product": blood_data.blood_product,
                "quantity": blood_data.quantity,
                "blood_bank_id": str(blood_bank_id),
                "duration_ms": duration_ms
            },
            user_id=user_id,
            ip_address=client_ip
        )
        
        log_audit_event(
            action="create",
            resource_type="blood_inventory",
            resource_id=str(new_blood_unit.id),
            new_values={
                "blood_type": blood_data.blood_type,
                "blood_product": blood_data.blood_product,
                "quantity": blood_data.quantity,
                "expiry_date": blood_data.expiry_date.isoformat(),
                "blood_bank_id": str(blood_bank_id),
                "added_by_id": user_id
            },
            user_id=user_id
        )
        
        logger.info(
            "Blood unit creation successful",
            extra={
                "event_type": "blood_unit_created",
                "user_id": user_id,
                "blood_unit_id": str(new_blood_unit.id),
                "blood_type": blood_data.blood_type,
                "quantity": blood_data.quantity,
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow operations
        if duration_ms > 2000:  # More than 2 seconds
            log_performance_metric(
                operation="blood_unit_creation",
                duration_seconds=duration_ms,
                additional_metrics={
                    "slow_operation": True,
                    "blood_type": blood_data.blood_type,
                    "quantity": blood_data.quantity
                }
            )

        return BloodInventoryResponse.model_validate(new_blood_unit, from_attributes=True)
        
    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Blood unit creation failed due to unexpected error",
            extra={
                "event_type": "blood_unit_creation_error",
                "user_id": user_id,
                "blood_type": blood_data.blood_type,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        log_security_event(
            event_type="blood_unit_creation_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "blood_type": blood_data.blood_type,
                "duration_ms": duration_ms
            },
            user_id=user_id,
            ip_address=client_ip
        )
        
        raise HTTPException(status_code=500, detail=f"Blood unit creation failed {str(e)}")


@router.post("/batch", response_model=BatchOperationResponse, status_code=status.HTTP_201_CREATED)
async def batch_create_blood_units(
    batch_data: BloodInventoryBatchCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "inventory.manage",
        "blood.inventory.manage"
    ))
):
    """
    Batch create multiple blood units.
    Handles up to 1000 units per request with transaction safety.
    """
    start_time = time.time()
    user_id = str(current_user.id)
    client_ip = get_client_ip(request)
    units_count = len(batch_data.blood_units)

    logger.info(
        "Batch blood unit creation started",
        extra={
            "event_type": "batch_blood_unit_creation_attempt",
            "user_id": user_id,
            "units_count": units_count,
            "client_ip": client_ip
        }
    )

    try:
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)

        if not blood_bank_id:
            log_security_event(
                event_type="batch_blood_unit_creation_denied",
                details={
                    "reason": "no_blood_bank_access",
                    "user_id": user_id,
                    "attempted_units": units_count
                },
                user_id=user_id,
                ip_address=client_ip
            )

            logger.warning(
                "Batch blood unit creation denied - no blood bank access",
                extra={
                    "event_type": "batch_blood_unit_creation_denied",
                    "user_id": user_id,
                    "units_count": units_count,
                    "reason": "no_blood_bank_access"
                }
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not belong to any facility or blood bank. Please contact admin."
            )

        blood_service = BloodInventoryService(db)

        created_units = await blood_service.batch_create_blood_units(
            blood_units_data=batch_data.blood_units,
            blood_bank_id=blood_bank_id,
            added_by_id=current_user.id
        )

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        created_count = len(created_units)

        # Log successful batch creation
        log_security_event(
            event_type="batch_blood_units_created",
            details={
                "created_count": created_count,
                "requested_count": units_count,
                "blood_bank_id": str(blood_bank_id),
                "duration_ms": duration_ms,
                "success_rate": (created_count / units_count) * 100
            },
            user_id=user_id,
            ip_address=client_ip
        )

        log_audit_event(
            action="batch_create",
            resource_type="blood_inventory",
            resource_id=f"batch_{len(created_units)}_units",
            new_values={
                "created_count": created_count,
                "blood_bank_id": str(blood_bank_id),
                "unit_ids": [str(unit.id) for unit in created_units]
            },
            user_id=user_id
        )

        logger.info(
            "Batch blood unit creation successful",
            extra={
                "event_type": "batch_blood_units_created",
                "user_id": user_id,
                "created_count": created_count,
                "requested_count": units_count,
                "blood_bank_id": str(blood_bank_id),
                "duration_ms": duration_ms
            }
        )

        # Log performance metrics
        log_performance_metric(
            operation="batch_blood_unit_creation",
            duration_seconds=duration_ms,
            additional_metrics={
                "units_created": created_count,
                "units_per_second": created_count / (duration_ms / 1000) if duration_ms > 0 else 0,
                "batch_efficiency": (created_count / units_count) * 100
            }
        )

        return BatchOperationResponse(
            success=True,
            processed_count=created_count,
            created_ids=[unit.id for unit in created_units]
        )

    except Exception as e:
        # Calculate duration for error case
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Batch blood unit creation failed",
            extra={
                "event_type": "batch_blood_unit_creation_error",
                "user_id": user_id,
                "units_count": units_count,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )

        log_security_event(
            event_type="batch_blood_unit_creation_error",
            details={
                "reason": "operation_failed",
                "error": str(e),
                "units_count": units_count,
                "duration_ms": duration_ms
            },
            user_id=user_id,
            ip_address=client_ip
        )

        return BatchOperationResponse(
            success=False,
            processed_count=0,
            failed_count=units_count,
            errors=[str(e)]
        )


@router.get("/facilities/search-stock", response_model=PaginatedFacilityResponse)
async def get_facilities_with_available_blood(
    request: Request,
    blood_type: Annotated[
        Optional[str],
        Query(
            description="Blood type to filter by (e.g., A+, B-). If not provided, returns all blood types."
        ),
    ] = None,
    blood_product: Annotated[
        Optional[str],
        Query(
            description="Blood product to filter by (e.g., Whole Blood, Plasma). If not provided, returns all products."
        ),
    ] = None,
    pagination: PaginationParams = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "any"
        )
    ),
):
    """
    Get paginated list of unique facilities (excluding user's own facility) that have available blood inventory.
    If blood_type and blood_product are provided, filters by those criteria.
    If not provided, returns all facilities with any available blood inventory.
    Returns only facility ID and name for efficient response.
    """
    start_time = time.time()
    client_ip = get_client_ip(request)
    user_id = str(current_user.id)

    logger.info(
        "Facilities with blood stock search started",
        extra={
            "event_type": "facilities_blood_search_attempt",
            "user_id": user_id,
            "blood_type": blood_type,
            "blood_product": blood_product,
            "page": pagination.page,
            "page_size": pagination.page_size,
            "client_ip": client_ip,
        },
    )

    try:
        # Get user's blood bank ID to exclude their facility
        user_blood_bank_id = await get_user_blood_bank_id(db, current_user.id)

        blood_service = BloodInventoryService(db)
        result = await blood_service.get_facilities_with_available_blood(
            blood_type=blood_type,
            blood_product=blood_product,
            pagination=pagination,
            exclude_user_blood_bank_id=user_blood_bank_id,  # Pass user's blood bank ID to exclude
        )

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "Facilities with blood stock search successful",
            extra={
                "event_type": "facilities_blood_search_success",
                "user_id": user_id,
                "blood_type": blood_type,
                "blood_product": blood_product,
                "facilities_found": (
                    len(result.items) if hasattr(result, "items") else 0
                ),
                "excluded_user_facility": user_blood_bank_id is not None,
                "duration_ms": duration_ms,
            },
        )

        # Log performance metric for slow queries
        if duration_ms > 1000:  # More than 1 second
            log_performance_metric(
                operation="facilities_blood_search",
                duration_seconds=duration_ms,
                additional_metrics={
                    "slow_query": True,
                    "blood_type": blood_type,
                    "blood_product": blood_product,
                    "page_size": pagination.page_size,
                },
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Facilities with blood stock search failed",
            extra={
                "event_type": "facilities_blood_search_error",
                "user_id": user_id,
                "blood_type": blood_type,
                "blood_product": blood_product,
                "error": str(e),
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch facility data",
        )


@router.patch("/batch", response_model=BatchOperationResponse)
async def batch_update_blood_units(
    batch_data: BloodInventoryBatchUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
        "facility.manage",
        "inventory.manage",
        "blood.inventory.manage"
    ))
):
    """
    Batch update multiple blood units with comprehensive logging.
    Each update must include the unit ID and fields to update.
    """
    start_time = time.time()
    user_id = str(current_user.id)
    client_ip = get_client_ip(request)
    updates_count = len(batch_data.updates)
    
    logger.info(
        "Batch blood unit update started",
        extra={
            "event_type": "batch_blood_unit_update_attempt",
            "user_id": user_id,
            "updates_count": updates_count,
            "client_ip": client_ip
        }
    )
    
    try:
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
        blood_service = BloodInventoryService(db)

        # Verify all units belong to the user's blood bank
        unit_ids = [update['id'] for update in batch_data.updates]
        
        # Check ownership
        result = await db.execute(
            select(BloodInventory.id, BloodInventory.blood_bank_id)
            .where(BloodInventory.id.in_(unit_ids))
        )
        units_check = result.all()
        
        unauthorized_units = [
            str(unit.id) for unit in units_check 
            if unit.blood_bank_id != blood_bank_id
        ]
        
        if unauthorized_units:
            log_security_event(
                event_type="batch_blood_unit_update_denied",
                details={
                    "reason": "unauthorized_units",
                    "unauthorized_unit_ids": unauthorized_units,
                    "user_blood_bank_id": str(blood_bank_id)
                },
                user_id=user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Batch blood unit update denied - unauthorized units",
                extra={
                    "event_type": "batch_blood_unit_update_denied",
                    "user_id": user_id,
                    "unauthorized_units": unauthorized_units,
                    "reason": "unauthorized_units"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You don't have permission to update units: {unauthorized_units}"
            )
        
        updated_units = await blood_service.batch_update_blood_units(batch_data.updates)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        updated_count = len(updated_units)
        
        # Log successful batch update
        log_security_event(
            event_type="batch_blood_units_updated",
            details={
                "updated_count": updated_count,
                "requested_count": updates_count,
                "blood_bank_id": str(blood_bank_id),
                "duration_ms": duration_ms
            },
            user_id=user_id,
            ip_address=client_ip
        )
        
        log_audit_event(
            action="batch_update",
            resource_type="blood_inventory",
            resource_id=f"batch_{updated_count}_units",
            new_values={
                "updated_count": updated_count,
                "blood_bank_id": str(blood_bank_id),
                "unit_ids": [str(unit.id) for unit in updated_units]
            },
            user_id=user_id
        )
        
        logger.info(
            "Batch blood unit update successful",
            extra={
                "event_type": "batch_blood_units_updated",
                "user_id": user_id,
                "updated_count": updated_count,
                "requested_count": updates_count,
                "duration_ms": duration_ms
            }
        )
        
        return BatchOperationResponse(
            success=True,
            processed_count=updated_count
        )
    
    except Exception as e:
        # Calculate duration for error case
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Batch blood unit update failed",
            extra={
                "event_type": "batch_blood_unit_update_error",
                "user_id": user_id,
                "updates_count": updates_count,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        return BatchOperationResponse(
            success=False,
            processed_count=0,
            failed_count=updates_count,
            errors=[str(e)]
        )

@router.delete("/batch", response_model=BatchOperationResponse)
async def batch_delete_blood_units(
    batch_data: BloodInventoryBatchDelete,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
        "facility.manage",
        "inventory.manage",
        "blood.inventory.manage"
    ))
):
    """
    Batch delete multiple blood units with comprehensive logging.
    User must own all units being deleted.
    """
    start_time = time.time()
    user_id = str(current_user.id)
    client_ip = get_client_ip(request)
    units_count = len(batch_data.unit_ids)
    
    logger.info(
        "Batch blood unit deletion started",
        extra={
            "event_type": "batch_blood_unit_deletion_attempt",
            "user_id": user_id,
            "units_count": units_count,
            "client_ip": client_ip
        }
    )
    
    try:
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
        
        if not blood_bank_id:
            log_security_event(
                event_type="batch_blood_unit_deletion_denied",
                details={
                    "reason": "no_blood_bank_access",
                    "user_id": user_id,
                    "attempted_units": units_count
                },
                user_id=user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Batch blood unit deletion denied - no blood bank access",
                extra={
                    "event_type": "batch_blood_unit_deletion_denied",
                    "user_id": user_id,
                    "units_count": units_count,
                    "reason": "no_blood_bank_access"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not belong to any facility or blood bank. Please contact admin."
            )
        
        blood_service = BloodInventoryService(db)
        
        # Verify ownership
        result = await db.execute(
            select(BloodInventory.id, BloodInventory.blood_bank_id)
            .where(BloodInventory.id.in_(batch_data.unit_ids))
        )
        units_check = result.all()
        
        unauthorized_units = [
            str(unit.id) for unit in units_check 
            if unit.blood_bank_id != blood_bank_id
        ]
        
        if unauthorized_units:
            log_security_event(
                event_type="batch_blood_unit_deletion_denied",
                details={
                    "reason": "unauthorized_units",
                    "unauthorized_unit_ids": unauthorized_units,
                    "user_blood_bank_id": str(blood_bank_id),
                    "attempted_count": units_count
                },
                user_id=user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Batch blood unit deletion denied - unauthorized units",
                extra={
                    "event_type": "batch_blood_unit_deletion_denied",
                    "user_id": user_id,
                    "unauthorized_units": unauthorized_units,
                    "units_count": units_count,
                    "reason": "unauthorized_units"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You don't have permission to delete units: {unauthorized_units}"
            )
        
        deleted_count = await blood_service.batch_delete_blood_units(batch_data.unit_ids)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Log successful batch deletion
        log_security_event(
            event_type="batch_blood_units_deleted",
            details={
                "deleted_count": deleted_count,
                "requested_count": units_count,
                "blood_bank_id": str(blood_bank_id),
                "duration_ms": duration_ms,
                "unit_ids": [str(uid) for uid in batch_data.unit_ids]
            },
            user_id=user_id,
            ip_address=client_ip
        )
        
        log_audit_event(
            action="batch_delete",
            resource_type="blood_inventory",
            resource_id=f"batch_{deleted_count}_units",
            old_values={
                "deleted_count": deleted_count,
                "blood_bank_id": str(blood_bank_id),
                "unit_ids": [str(uid) for uid in batch_data.unit_ids]
            },
            new_values=None,
            user_id=user_id
        )
        
        logger.info(
            "Batch blood unit deletion successful",
            extra={
                "event_type": "batch_blood_units_deleted",
                "user_id": user_id,
                "deleted_count": deleted_count,
                "requested_count": units_count,
                "blood_bank_id": str(blood_bank_id),
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metrics
        log_performance_metric(
            operation="batch_blood_unit_deletion",
            duration_seconds=duration_ms,
            additional_metrics={
                "units_deleted": deleted_count,
                "deletion_rate": deleted_count / (duration_ms / 1000) if duration_ms > 0 else 0,
                "batch_efficiency": (deleted_count / units_count) * 100
            }
        )
        
        return BatchOperationResponse(
            success=True,
            processed_count=deleted_count
        )
    
    except Exception as e:
        # Calculate duration for error case
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Batch blood unit deletion failed",
            extra={
                "event_type": "batch_blood_unit_deletion_error",
                "user_id": user_id,
                "units_count": units_count,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        log_security_event(
            event_type="batch_blood_unit_deletion_error",
            details={
                "reason": "operation_failed",
                "error": str(e),
                "units_count": units_count,
                "duration_ms": duration_ms
            },
            user_id=user_id,
            ip_address=client_ip
        )
        
        return BatchOperationResponse(
            success=False,
            processed_count=0,
            failed_count=units_count,
            errors=[str(e)]
        )


@router.get("/{blood_unit_id}", response_model=BloodInventoryDetailResponse)
async def get_blood_unit(
    blood_unit_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific blood unit with logging"""
    start_time = time.time()
    unit_id = str(blood_unit_id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "Blood unit detail request started",
        extra={
            "event_type": "blood_unit_detail_attempt",
            "blood_unit_id": unit_id,
            "client_ip": client_ip
        }
    )
    
    try:
        blood_service = BloodInventoryService(db)
        blood_unit = await blood_service.get_blood_unit(blood_unit_id)
        
        if not blood_unit:
            logger.warning(
                "Blood unit detail request failed - unit not found",
                extra={
                    "event_type": "blood_unit_detail_failed",
                    "blood_unit_id": unit_id,
                    "reason": "unit_not_found"
                }
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blood unit not found"
            )
        
        response = BloodInventoryDetailResponse(
            **BloodInventoryResponse.model_validate(blood_unit, from_attributes=True).model_dump(),
            blood_bank_name=blood_unit.blood_bank.blood_bank_name if blood_unit.blood_bank else None,
            added_by_name=blood_unit.added_by.last_name if blood_unit.added_by else None
        )
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "Blood unit detail request successful",
            extra={
                "event_type": "blood_unit_detail_retrieved",
                "blood_unit_id": unit_id,
                "blood_type": blood_unit.blood_type,
                "blood_product": blood_unit.blood_product,
                "duration_ms": duration_ms
            }
        )
        
        return response
        
    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Blood unit detail request failed due to unexpected error",
            extra={
                "event_type": "blood_unit_detail_error",
                "blood_unit_id": unit_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve blood unit details")


@router.get("/", response_model=PaginatedResponse[BloodInventoryDetailResponse])
async def facility_blood_inventory(
    request: Request,
    pagination: PaginationParams = Depends(get_pagination_params),
    blood_type: Annotated[Optional[str], Query(description="Filter by blood type")] = None,
    blood_product: Annotated[Optional[str], Query(description="Filter by blood product")] = None,
    expiry_date_from: Annotated[Optional[datetime], Query(description="Filter by expiry date from")] = None,
    expiry_date_to: Annotated[Optional[datetime], Query(description="Filter by expiry date to")] = None,
    search_term: Annotated[Optional[str], Query(description="Search in blood type and product")] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """
    List blood units with comprehensive pagination and filtering and logging.
    Ensures the user is associated with a facility and blood bank.
    """
    start_time = time.time()
    user_id = str(current_user.id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "Blood inventory listing started",
        extra={
            "event_type": "blood_inventory_list_attempt",
            "user_id": user_id,
            "filters": {
                "blood_type": blood_type,
                "blood_product": blood_product,
                "search_term": search_term,
                "page": pagination.page,
                "page_size": pagination.page_size
            },
            "client_ip": client_ip
        }
    )
    
    try:
        # Get user's blood bank ID
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)

        if not blood_bank_id:
            log_security_event(
                event_type="blood_inventory_access_denied",
                details={
                    "reason": "no_blood_bank_access",
                    "user_id": user_id
                },
                user_id=user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood inventory access denied - no blood bank access",
                extra={
                    "event_type": "blood_inventory_access_denied",
                    "user_id": user_id,
                    "reason": "no_blood_bank_access"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not belong to any facility or blood bank. Please contact admin."
            )

        # Proceed with fetching blood inventory
        blood_service = BloodInventoryService(db)

        result = await blood_service.get_paginated_blood_units(
            pagination=pagination,
            current_user_blood_bank_id=blood_bank_id,
            blood_type=blood_type,
            blood_product=blood_product,
            expiry_date_from=expiry_date_from,
            expiry_date_to=expiry_date_to,
            search_term=search_term
        )

        detailed_items = [
            BloodInventoryDetailResponse(
                **BloodInventoryResponse.model_validate(unit, from_attributes=True).model_dump(),
                blood_bank_name=unit.blood_bank.blood_bank_name if unit.blood_bank else None,
                added_by_name=unit.added_by.last_name if unit.added_by else None
            )
            for unit in result.items
        ]
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "Blood inventory listing successful",
            extra={
                "event_type": "blood_inventory_listed",
                "user_id": user_id,
                "blood_bank_id": str(blood_bank_id),
                "items_returned": len(detailed_items),
                "total_items": result.total_items,
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow queries
        if duration_ms > 1000:  # More than 1 second
            log_performance_metric(
                operation="blood_inventory_listing",
                duration_seconds=duration_ms,
                additional_metrics={
                    "slow_query": True,
                    "result_count": len(detailed_items),
                    "filters_applied": bool(blood_type or blood_product or search_term),
                    "page_size": pagination.page_size
                }
            )

        return PaginatedResponse(
            items=detailed_items,
            total_items=result.total_items,
            total_pages=result.total_pages,
            current_page=result.current_page,
            page_size=result.page_size,
            has_next=result.has_next,
            has_prev=result.has_prev
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Blood inventory listing failed due to unexpected error",
            extra={
                "event_type": "blood_inventory_list_error",
                "user_id": user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve blood inventory")


@router.post("/advanced-search", response_model=PaginatedResponse[BloodInventoryDetailResponse])
async def advanced_search_blood_units(
    search_params: BloodInventorySearchParams,
    request: Request,
    pagination: PaginationParams = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db)
):
    """
    Advanced search for blood units with multiple filter combinations and logging.
    Supports complex queries and multiple selection criteria.
    """
    start_time = time.time()
    client_ip = get_client_ip(request)
    
    logger.info(
        "Advanced blood unit search started",
        extra={
            "event_type": "advanced_blood_search_attempt",
            "search_filters": {
                "blood_types": search_params.blood_types,
                "blood_products": search_params.blood_products,
                "search_term": search_params.search_term,
                "min_quantity": search_params.min_quantity,
                "max_quantity": search_params.max_quantity
            },
            "pagination": {
                "page": pagination.page,
                "page_size": pagination.page_size
            },
            "client_ip": client_ip
        }
    )
    
    try:
        blood_service = BloodInventoryService(db)
        
        # Convert search params to service method parameters
        result = await blood_service.get_paginated_blood_units(
            pagination=pagination,
            blood_type=search_params.blood_types[0] if search_params.blood_types else None,
            blood_product=search_params.blood_products[0] if search_params.blood_products else None,
            expiry_date_from=datetime.combine(search_params.expiry_date_from, datetime.min.time()) if search_params.expiry_date_from else None,
            expiry_date_to=datetime.combine(search_params.expiry_date_to, datetime.min.time()) if search_params.expiry_date_to else None,
            search_term=search_params.search_term
        )
        
        # Additional filtering for complex criteria
        if search_params.blood_types and len(search_params.blood_types) > 1:
            result.items = [item for item in result.items if item.blood_type in search_params.blood_types]
        
        if search_params.blood_products and len(search_params.blood_products) > 1:
            result.items = [item for item in result.items if item.blood_product in search_params.blood_products]
        
        if search_params.min_quantity is not None:
            result.items = [item for item in result.items if item.quantity >= search_params.min_quantity]
        
        if search_params.max_quantity is not None:
            result.items = [item for item in result.items if item.quantity <= search_params.max_quantity]
        
        # Transform to detailed response
        detailed_items = [
            BloodInventoryDetailResponse(
                **BloodInventoryResponse.model_validate(unit, from_attributes=True).model_dump(),
                blood_bank_name=unit.blood_bank.blood_bank_name if unit.blood_bank else None,
                added_by_name=unit.added_by.last_name if unit.added_by else None
            )
            for unit in result.items
        ]
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        results_count = len(detailed_items)
        
        logger.info(
            "Advanced blood unit search successful",
            extra={
                "event_type": "advanced_blood_search_completed",
                "results_count": results_count,
                "total_filters": len([f for f in [
                    search_params.blood_types,
                    search_params.blood_products,
                    search_params.search_term,
                    search_params.min_quantity,
                    search_params.max_quantity
                ] if f]),
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow searches
        if duration_ms > 2000:  # More than 2 seconds
            log_performance_metric(
                operation="advanced_blood_search",
                duration_seconds=duration_ms,
                additional_metrics={
                    "slow_search": True,
                    "results_count": results_count,
                    "complex_filters": len(search_params.blood_types or []) + len(search_params.blood_products or []) > 2
                }
            )
        
        return PaginatedResponse(
            items=detailed_items,
            total_items=len(detailed_items),
            total_pages=(len(detailed_items) + pagination.page_size - 1) // pagination.page_size,
            current_page=pagination.page,
            page_size=pagination.page_size,
            has_next=pagination.page * pagination.page_size < len(detailed_items),
            has_prev=pagination.page > 1
        )
        
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Advanced blood unit search failed due to unexpected error",
            extra={
                "event_type": "advanced_blood_search_error",
                "search_filters": {
                    "blood_types": search_params.blood_types,
                    "blood_products": search_params.blood_products
                },
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Advanced search failed")


@router.patch("/{blood_unit_id}", response_model=BloodInventoryResponse)
async def update_blood_unit(
    blood_unit_id: UUID,
    blood_data: BloodInventoryUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
        "facility.manage",
        "inventory.manage",
        "blood.inventory.manage"
    ))
):
    """
    Update a blood unit with comprehensive logging.
    User must be associated with the blood bank that owns this unit.
    """
    start_time = time.time()
    user_id = str(current_user.id)
    unit_id = str(blood_unit_id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "Blood unit update started",
        extra={
            "event_type": "blood_unit_update_attempt",
            "user_id": user_id,
            "blood_unit_id": unit_id,
            "client_ip": client_ip
        }
    )
    
    try:
        blood_service = BloodInventoryService(db)
        blood_unit = await blood_service.get_blood_unit(blood_unit_id)
        
        if not blood_unit:
            logger.warning(
                "Blood unit update failed - unit not found",
                extra={
                    "event_type": "blood_unit_update_failed",
                    "user_id": user_id,
                    "blood_unit_id": unit_id,
                    "reason": "unit_not_found"
                }
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blood unit not found"
            )
        
        user_blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
        
        if blood_unit.blood_bank_id != user_blood_bank_id:
            log_security_event(
                event_type="blood_unit_update_denied",
                details={
                    "reason": "unauthorized_access",
                    "blood_unit_id": unit_id,
                    "user_blood_bank_id": str(user_blood_bank_id),
                    "unit_blood_bank_id": str(blood_unit.blood_bank_id)
                },
                user_id=user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood unit update denied - unauthorized access",
                extra={
                    "event_type": "blood_unit_update_denied",
                    "user_id": user_id,
                    "blood_unit_id": unit_id,
                    "reason": "unauthorized_access"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update this blood unit"
            )
        
        # Store old values for audit
        old_values = {
            "blood_type": blood_unit.blood_type,
            "blood_product": blood_unit.blood_product,
            "quantity": blood_unit.quantity,
            "expiry_date": blood_unit.expiry_date.isoformat()
        }
        
        updated_unit = await blood_service.update_blood_unit(blood_unit_id, blood_data)
        
        # Store new values for audit
        new_values = {
            "blood_type": updated_unit.blood_type,
            "blood_product": updated_unit.blood_product,
            "quantity": updated_unit.quantity,
            "expiry_date": updated_unit.expiry_date.isoformat()
        }
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Log successful update
        log_security_event(
            event_type="blood_unit_updated",
            details={
                "blood_unit_id": unit_id,
                "duration_ms": duration_ms,
                "fields_updated": list(blood_data.model_dump(exclude_unset=True).keys())
            },
            user_id=user_id,
            ip_address=client_ip
        )
        
        log_audit_event(
            action="update",
            resource_type="blood_inventory",
            resource_id=unit_id,
            old_values=old_values,
            new_values=new_values,
            user_id=user_id
        )
        
        logger.info(
            "Blood unit update successful",
            extra={
                "event_type": "blood_unit_updated",
                "user_id": user_id,
                "blood_unit_id": unit_id,
                "fields_updated": list(blood_data.model_dump(exclude_unset=True).keys()),
                "duration_ms": duration_ms
            }
        )
        
        return BloodInventoryResponse.model_validate(updated_unit, from_attributes=True)
        
    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Blood unit update failed due to unexpected error",
            extra={
                "event_type": "blood_unit_update_error",
                "user_id": user_id,
                "blood_unit_id": unit_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Blood unit update failed")


@router.delete("/{blood_unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blood_unit(
    blood_unit_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
        "facility.manage",
        "inventory.manage",
        "blood.inventory.manage"
    ))
):
    """
    Delete a blood unit with comprehensive logging.
    User must be associated with the blood bank that owns this unit.
    """
    start_time = time.time()
    user_id = str(current_user.id)
    unit_id = str(blood_unit_id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "Blood unit deletion started",
        extra={
            "event_type": "blood_unit_deletion_attempt",
            "user_id": user_id,
            "blood_unit_id": unit_id,
            "client_ip": client_ip
        }
    )
    
    try:
        blood_service = BloodInventoryService(db)
        blood_unit = await blood_service.get_blood_unit(blood_unit_id)
        
        if not blood_unit:
            logger.warning(
                "Blood unit deletion failed - unit not found",
                extra={
                    "event_type": "blood_unit_deletion_failed",
                    "user_id": user_id,
                    "blood_unit_id": unit_id,
                    "reason": "unit_not_found"
                }
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blood unit not found"
            )
        
        user_blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
        
        if blood_unit.blood_bank_id != user_blood_bank_id:
            log_security_event(
                event_type="blood_unit_deletion_denied",
                details={
                    "reason": "unauthorized_access",
                    "blood_unit_id": unit_id,
                    "user_blood_bank_id": str(user_blood_bank_id),
                    "unit_blood_bank_id": str(blood_unit.blood_bank_id)
                },
                user_id=user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood unit deletion denied - unauthorized access",
                extra={
                    "event_type": "blood_unit_deletion_denied",
                    "user_id": user_id,
                    "blood_unit_id": unit_id,
                    "reason": "unauthorized_access"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this blood unit"
            )
        
        # Store unit data for audit before deletion
        unit_data_for_audit = {
            "blood_type": blood_unit.blood_type,
            "blood_product": blood_unit.blood_product,
            "quantity": blood_unit.quantity,
            "expiry_date": blood_unit.expiry_date.isoformat(),
            "blood_bank_id": str(blood_unit.blood_bank_id)
        }
        
        await blood_service.delete_blood_unit(blood_unit_id)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Log successful deletion
        log_security_event(
            event_type="blood_unit_deleted",
            details={
                "blood_unit_id": unit_id,
                "blood_type": blood_unit.blood_type,
                "blood_product": blood_unit.blood_product,
                "duration_ms": duration_ms
            },
            user_id=user_id,
            ip_address=client_ip
        )
        
        log_audit_event(
            action="delete",
            resource_type="blood_inventory",
            resource_id=unit_id,
            old_values=unit_data_for_audit,
            new_values=None,
            user_id=user_id
        )
        
        logger.info(
            "Blood unit deletion successful",
            extra={
                "event_type": "blood_unit_deleted",
                "user_id": user_id,
                "blood_unit_id": unit_id,
                "blood_type": blood_unit.blood_type,
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
            "Blood unit deletion failed due to unexpected error",
            extra={
                "event_type": "blood_unit_deletion_error",
                "user_id": user_id,
                "blood_unit_id": unit_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Blood unit deletion failed")


@router.get("/expiring/{days}", response_model=PaginatedResponse[BloodInventoryDetailResponse])
async def get_expiring_blood_units_paginated(
    days: int = Path(..., ge=1, le=90, description="Number of days to check for expiration"),
    request: Request = None,
    pagination: PaginationParams = Depends(get_pagination_params),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
        "facility.manage",
        "inventory.manage",
        "blood.inventory.manage"
    ))
):
    """
    Get paginated blood units expiring in the specified number of days with logging.
    Only shows units from the blood bank associated with the current user.
    """
    start_time = time.time()
    user_id = str(current_user.id)
    client_ip = get_client_ip(request) if request else None
    
    logger.info(
        "Expiring blood units request started",
        extra={
            "event_type": "expiring_blood_units_attempt",
            "user_id": user_id,
            "days_threshold": days,
            "page": pagination.page,
            "page_size": pagination.page_size,
            "client_ip": client_ip
        }
    )
    
    try:
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
        
        if not blood_bank_id:
            log_security_event(
                event_type="expiring_blood_units_denied",
                details={
                    "reason": "no_blood_bank_access",
                    "user_id": user_id,
                    "days_threshold": days
                },
                user_id=user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Expiring blood units access denied - no blood bank access",
                extra={
                    "event_type": "expiring_blood_units_denied",
                    "user_id": user_id,
                    "days_threshold": days,
                    "reason": "no_blood_bank_access"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not belong to any facility or blood bank. Please contact admin."
            )
        
        blood_service = BloodInventoryService(db)
        result = await blood_service.get_expiring_blood_units(days, pagination)
        
        if isinstance(result, list):
            # Filter by user's blood bank
            filtered_units = [unit for unit in result if unit.blood_bank_id == blood_bank_id]
            
            detailed_items = [
                BloodInventoryDetailResponse(
                    **BloodInventoryResponse.model_validate(unit, from_attributes=True).model_dump(),
                    blood_bank_name=unit.blood_bank.blood_bank_name if unit.blood_bank else None,
                    added_by_name=unit.added_by.last_name if unit.added_by else None
                )
                for unit in filtered_units
            ]
            
            paginated_result = PaginatedResponse(
                items=detailed_items,
                total_items=len(detailed_items),
                total_pages=1,
                current_page=1,
                page_size=len(detailed_items),
                has_next=False,
                has_prev=False
            )
        else:
            # Filter paginated result by user's blood bank
            filtered_items = [unit for unit in result.items if unit.blood_bank_id == blood_bank_id]
            
            detailed_items = [
                BloodInventoryDetailResponse(
                    **BloodInventoryResponse.model_validate(unit, from_attributes=True).model_dump(),
                    blood_bank_name=unit.blood_bank.blood_bank_name if unit.blood_bank else None,
                    added_by_name=unit.added_by.last_name if unit.added_by else None
                )
                for unit in filtered_items
            ]
            
            paginated_result = PaginatedResponse(
                items=detailed_items,
                total_items=len(detailed_items),
                total_pages=(len(detailed_items) + pagination.page_size - 1) // pagination.page_size,
                current_page=pagination.page,
                page_size=pagination.page_size,
                has_next=pagination.page * pagination.page_size < len(detailed_items),
                has_prev=pagination.page > 1
            )
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        expiring_count = len(detailed_items)
        
        logger.info(
            "Expiring blood units request successful",
            extra={
                "event_type": "expiring_blood_units_retrieved",
                "user_id": user_id,
                "blood_bank_id": str(blood_bank_id),
                "days_threshold": days,
                "expiring_count": expiring_count,
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow queries
        if duration_ms > 1000:  # More than 1 second
            log_performance_metric(
                operation="expiring_blood_units_query",
                duration_seconds=duration_ms,
                additional_metrics={
                    "slow_query": True,
                    "days_threshold": days,
                    "result_count": expiring_count,
                    "blood_bank_id": str(blood_bank_id)
                }
            )
        
        # Log alert if many units are expiring
        if expiring_count > 10:
            log_security_event(
                event_type="high_expiring_units_alert",
                details={
                    "expiring_count": expiring_count,
                    "days_threshold": days,
                    "blood_bank_id": str(blood_bank_id),
                    "alert_level": "high" if expiring_count > 50 else "medium"
                },
                user_id=user_id,
                ip_address=client_ip
            )
        
        return paginated_result
        
    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Expiring blood units request failed due to unexpected error",
            extra={
                "event_type": "expiring_blood_units_error",
                "user_id": user_id,
                "days_threshold": days,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve expiring blood units")


@router.get("/statistics/overview", response_model=InventoryStatistics)
async def get_inventory_statistics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
        "facility.manage",
        "inventory.manage"
    ))
):
    """
    Get comprehensive inventory statistics with logging.
    If blood_bank_id is not provided, uses the current user's blood bank.
    """
    start_time = time.time()
    user_id = str(current_user.id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "Inventory statistics request started",
        extra={
            "event_type": "inventory_statistics_attempt",
            "user_id": user_id,
            "client_ip": client_ip
        }
    )
    
    try:
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
        
        if not blood_bank_id:
            log_security_event(
                event_type="inventory_statistics_denied",
                details={
                    "reason": "no_blood_bank_access",
                    "user_id": user_id
                },
                user_id=user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Inventory statistics access denied - no blood bank access",
                extra={
                    "event_type": "inventory_statistics_denied",
                    "user_id": user_id,
                    "reason": "no_blood_bank_access"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not belong to any facility or blood bank. Please contact admin."
            )
        
        blood_service = BloodInventoryService(db)
        stats = await blood_service.get_inventory_statistics(blood_bank_id)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "Inventory statistics request successful",
            extra={
                "event_type": "inventory_statistics_retrieved",
                "user_id": user_id,
                "blood_bank_id": str(blood_bank_id),
                "total_units": stats.get("total_units", 0),
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow operations
        if duration_ms > 500:  # More than 500ms
            log_performance_metric(
                operation="inventory_statistics",
                duration_seconds=duration_ms,
                additional_metrics={
                    "slow_operation": True,
                    "blood_bank_id": str(blood_bank_id)
                }
            )
        
        return InventoryStatistics(**stats)
        
    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Inventory statistics request failed due to unexpected error",
            extra={
                "event_type": "inventory_statistics_error",
                "user_id": user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve inventory statistics")


@router.get("/export/csv")
async def export_inventory_csv(
    request: Request,
    blood_type: Optional[str] = Query(None, description="Filter by blood type"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "inventory.manage"
    ))
):
    """
    Export blood inventory data as CSV with comprehensive logging.
    Supports filtering and is optimized for large datasets.
    """
    start_time = time.time()
    user_id = str(current_user.id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "Inventory CSV export started",
        extra={
            "event_type": "inventory_csv_export_attempt",
            "user_id": user_id,
            "blood_type_filter": blood_type,
            "client_ip": client_ip
        }
    )
    
    try:
        from fastapi.responses import StreamingResponse
        import csv
        import io
        
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
        
        if not blood_bank_id:
            log_security_event(
                event_type="inventory_export_denied",
                details={
                    "reason": "no_blood_bank_access",
                    "user_id": user_id,
                    "export_type": "csv"
                },
                user_id=user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Inventory CSV export denied - no blood bank access",
                extra={
                    "event_type": "inventory_export_denied",
                    "user_id": user_id,
                    "reason": "no_blood_bank_access"
                }
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not belong to any facility or blood bank. Please contact admin."
            )
        
        blood_service = BloodInventoryService(db)
        
        # Get all units (without pagination for export)
        if blood_type:
            units = await blood_service.get_blood_units_by_type(blood_type)
        else:
            units = await blood_service.get_blood_units_by_bank(blood_bank_id)
        
        # Filter by blood bank if needed
        if blood_bank_id:
            units = [unit for unit in units if unit.blood_bank_id == blood_bank_id]
        
        # Create CSV content
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'ID', 'Blood Product', 'Blood Type', 'Quantity', 'Expiry Date',
            'Blood Bank', 'Added By', 'Created At', 'Updated At'
        ])
        
        # Write data
        export_count = 0
        for unit in units:
            writer.writerow([
                str(unit.id),
                unit.blood_product,
                unit.blood_type,
                unit.quantity,
                unit.expiry_date.isoformat(),
                unit.blood_bank.blood_bank_name if unit.blood_bank else '',
                unit.added_by.last_name if unit.added_by else '',
                unit.created_at.isoformat(),
                unit.updated_at.isoformat()
            ])
            export_count += 1
        
        output.seek(0)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Log successful export
        log_security_event(
            event_type="inventory_exported",
            details={
                "export_type": "csv",
                "records_exported": export_count,
                "blood_type_filter": blood_type,
                "blood_bank_id": str(blood_bank_id),
                "duration_ms": duration_ms
            },
            user_id=user_id,
            ip_address=client_ip
        )
        
        log_audit_event(
            action="export",
            resource_type="blood_inventory",
            resource_id=f"csv_export_{export_count}_records",
            new_values={
                "export_type": "csv",
                "records_count": export_count,
                "blood_type_filter": blood_type,
                "blood_bank_id": str(blood_bank_id)
            },
            user_id=user_id
        )
        
        logger.info(
            "Inventory CSV export successful",
            extra={
                "event_type": "inventory_csv_exported",
                "user_id": user_id,
                "records_exported": export_count,
                "blood_type_filter": blood_type,
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metrics
        log_performance_metric(
            operation="inventory_csv_export",
            duration_seconds=duration_ms,
            additional_metrics={
                "records_exported": export_count,
                "export_rate": export_count / (duration_ms / 1000) if duration_ms > 0 else 0,
                "file_size_estimate": len(output.getvalue())
            }
        )
        
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode('utf-8')),
            media_type='text/csv',
            headers={'Content-Disposition': 'attachment; filename=blood_inventory.csv'}
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Inventory CSV export failed due to unexpected error",
            extra={
                "event_type": "inventory_csv_export_error",
                "user_id": user_id,
                "blood_type_filter": blood_type,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="CSV export failed")
