from fastapi import (
    APIRouter, 
    Depends, 
    HTTPException, 
    status, 
    Query, 
    Request
)
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List, Optional
import time
from app.schemas.inventory import PaginatedResponse
from app.models.user import User
from app.dependencies import get_db
from app.schemas.request import (
    BloodRequestCreate, 
    BloodRequestUpdate,
    BloodRequestStatusUpdate, 
    BloodRequestResponse,
    BloodRequestGroupResponse,
    BloodRequestBulkCreateResponse,
    RequestDirection
)
from app.utils.permission_checker import require_permission
from app.services.request import BloodRequestService
from app.models.request import RequestStatus, ProcessingStatus
from app.utils.logging_config import (
    get_logger, 
    log_security_event, 
    log_audit_event, 
    log_performance_metric
)
from app.utils.ip_address_finder import get_client_ip

# Get logger for this module
logger = get_logger(__name__)

router = APIRouter(
    prefix="/requests",
    tags=["requests"]
)


@router.post(
    "/",
    response_model=BloodRequestBulkCreateResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_blood_request(
    request_data: BloodRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_create"
    ))
):
    """
    Create blood requests to multiple 
    facilities with comprehensive logging
    """
    start_time = time.time()
    current_user_id = str(current_user.id)
    client_ip = get_client_ip(request)

    logger.info(
        "Blood request creation started",
        extra={
            "event_type": "blood_request_creation_attempt",
            "current_user_id": current_user_id,
            "blood_type": request_data.blood_type,
            "quantity": request_data.quantity_requested,
            "priority": request_data.priority,
            "facility_count": len(request_data.facility_ids),
            "client_ip": client_ip
        }
    )

    try:
        service = BloodRequestService(db)
        result = await service.create_bulk_request(
            request_data,
            requester_id=current_user.id
        )

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful creation
        log_audit_event(
            action="create",
            resource_type="blood_request_bulk",
            resource_id=str(result.request_group_id),
            new_values={
                "blood_type": request_data.blood_type,
                "quantity": request_data.quantity_requested,
                "priority": request_data.priority,
                "facility_count": len(request_data.facility_ids),
                "requests_created": len(result.requests)
            },
            user_id=current_user_id
        )

        logger.info(
            "Blood request creation successful",
            extra={
                "event_type": "blood_request_created",
                "current_user_id": current_user_id,
                "group_id": str(result.request_group_id),
                "requests_created": len(result.requests),
                "blood_type": request_data.blood_type,
                "quantity": request_data.quantity_requested,
                "duration_ms": duration_ms,
            },
        )

        # Log performance metric for slow operations
        if duration_ms > 2000:  # More than 2 seconds
            log_performance_metric(
                operation="blood_request_creation",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_operation": True,
                    "facility_count": len(request_data.facility_ids),
                    "requests_created": len(result.requests)
                }
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Blood request creation failed due to unexpected error",
            extra={
                "event_type": "blood_request_creation_error",
                "current_user_id": current_user_id,
                "blood_type": request_data.blood_type,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )

        log_security_event(
            event_type="blood_request_creation_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "blood_type": request_data.blood_type,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )

        raise HTTPException(
            status_code=500, 
            detail="Blood request creation failed"
        )


@router.get(
    "/my-requests", 
    response_model=List[BloodRequestResponse]
)
async def list_my_requests(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    ))
):
    """
    List all individual requests made by the current user.
    """
    start_time = time.time()
    current_user_id = str(current_user.id)
    
    logger.info(
        "My requests list access",
        extra={
            "event_type": "my_requests_access",
            "current_user_id": current_user_id
        }
    )
    
    try:
        service = BloodRequestService(db)
        requests = await service.list_requests_by_user(user_id=current_user.id)
        
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "My requests list access successful",
            extra={
                "event_type": "my_requests_accessed",
                "current_user_id": current_user_id,
                "request_count": len(requests),
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow queries
        if duration_ms > 1000:  # More than 1 second
            log_performance_metric(
                operation="get_my_requests",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_query": True,
                    "result_count": len(requests)
                }
            )
        
        return requests
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "My requests list access failed due to unexpected error",
            extra={
                "event_type": "my_requests_error",
                "current_user_id": current_user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve requests")


@router.get("/", response_model=PaginatedResponse[BloodRequestResponse])
async def list_facility_requests(
    request: Request,
    option: Optional[RequestDirection] = Query(RequestDirection.ALL, description="Filter requests by direction: 'received', 'sent', or 'all'"),
    request_status: Optional[RequestStatus] = Query(None, description="Filter by request status"),
    processing_status: Optional[ProcessingStatus] = Query(None, description="Filter by processing status"),
    page: int = Query(1, ge=1, description="Page number (starts from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page (max 100)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    ))
):
    """List requests with filtering and pagination."""
    start_time = time.time()
    current_user_id = str(current_user.id)
    
    logger.info(
        "Facility requests list access",
        extra={
            "event_type": "facility_requests_access",
            "current_user_id": current_user_id,
            "option": option.value if option else "all",
            "request_status": request_status.value if request_status else None,
            "processing_status": processing_status.value if processing_status else None,
            "page": page,
            "page_size": page_size
        }
    )
    
    try:
        service = BloodRequestService(db)
        
        result = await service.list_requests_by_facility(
            user_id=current_user.id,
            option=option.value if option else RequestDirection.ALL.value,
            request_status=request_status.value if request_status else None,
            processing_status=processing_status.value if processing_status else None,
            page=page,
            page_size=page_size
        )
        
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "Facility requests list access successful",
            extra={
                "event_type": "facility_requests_accessed",
                "current_user_id": current_user_id,
                "returned_items": len(result.items),
                "page": page,
                "page_size": page_size,
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow queries
        if duration_ms > 1500:  # More than 1.5 seconds
            log_performance_metric(
                operation="get_facility_requests",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_query": True,
                    "page_size": page_size,
                    "filters_applied": {
                        "option": option.value if option else None,
                        "request_status": request_status.value if request_status else None,
                        "processing_status": processing_status.value if processing_status else None
                    }
                }
            )
        
        return result
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Facility requests list access failed due to unexpected error",
            extra={
                "event_type": "facility_requests_error",
                "current_user_id": current_user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/groups", response_model=List[BloodRequestGroupResponse])
async def list_my_request_groups(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    ))
):
    """List request groups made by the current user."""
    start_time = time.time()
    current_user_id = str(current_user.id)
    
    logger.info(
        "Request groups list access",
        extra={
            "event_type": "request_groups_access",
            "current_user_id": current_user_id
        }
    )
    
    try:
        service = BloodRequestService(db)
        groups = await service.list_request_groups_by_user(user_id=current_user.id)
        
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "Request groups list access successful",
            extra={
                "event_type": "request_groups_accessed",
                "current_user_id": current_user_id,
                "group_count": len(groups),
                "duration_ms": duration_ms
            }
        )
        
        return groups
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Request groups list access failed due to unexpected error",
            extra={
                "event_type": "request_groups_error",
                "current_user_id": current_user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve request groups")


@router.get("/statistics")
async def get_request_statistics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage"
    ))
):
    """Get request statistics for the current user."""
    start_time = time.time()
    current_user_id = str(current_user.id)
    
    logger.info(
        "Request statistics access",
        extra={
            "event_type": "request_statistics_access",
            "current_user_id": current_user_id
        }
    )
    
    try:
        service = BloodRequestService(db)
        statistics = await service.get_request_statistics(user_id=current_user.id)
        
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "Request statistics access successful",
            extra={
                "event_type": "request_statistics_accessed",
                "current_user_id": current_user_id,
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow queries
        if duration_ms > 2000:  # More than 2 seconds
            log_performance_metric(
                operation="get_request_statistics",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_query": True,
                    "statistics_generated": True
                }
            )
        
        return statistics
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Request statistics access failed due to unexpected error",
            extra={
                "event_type": "request_statistics_error",
                "current_user_id": current_user_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve statistics")


@router.get("/groups/{request_group_id}", response_model=BloodRequestGroupResponse)
async def get_request_group(
    request_group_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    ))
):
    """Get detailed information about a request group."""
    start_time = time.time()
    current_user_id = str(current_user.id)
    group_id = str(request_group_id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "Request group access",
        extra={
            "event_type": "request_group_access",
            "current_user_id": current_user_id,
            "group_id": group_id
        }
    )
    
    try:
        service = BloodRequestService(db)
        group = await service.get_request_group(request_group_id)
        
        if not group:
            logger.warning(
                "Request group access failed - group not found",
                extra={
                    "event_type": "request_group_not_found",
                    "current_user_id": current_user_id,
                    "group_id": group_id
                }
            )
            raise HTTPException(status_code=404, detail="Request group not found")
        
        # Verify ownership
        if group.master_request.requester_id != current_user.id:
            log_security_event(
                event_type="unauthorized_request_group_access",
                details={
                    "reason": "not_owner",
                    "group_id": group_id,
                    "actual_owner": str(group.master_request.requester_id)
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Request group access denied - not authorized",
                extra={
                    "event_type": "request_group_access_denied",
                    "current_user_id": current_user_id,
                    "group_id": group_id,
                    "reason": "not_owner"
                }
            )
            
            raise HTTPException(status_code=403, detail="Not authorized to view this request group")
        
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "Request group access successful",
            extra={
                "event_type": "request_group_accessed",
                "current_user_id": current_user_id,
                "group_id": group_id,
                "duration_ms": duration_ms
            }
        )
        
        return group
        
    except HTTPException:
        raise
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Request group access failed due to unexpected error",
            extra={
                "event_type": "request_group_error",
                "current_user_id": current_user_id,
                "group_id": group_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve request group")


@router.get("/{request_id}", response_model=BloodRequestResponse)
async def get_blood_request(
    request_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    ))
):
    """Get blood request with authorization"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    req_id = str(request_id)
    client_ip = get_client_ip(request)

    logger.info(
        "Blood request access",
        extra={
            "event_type": "blood_request_access",
            "current_user_id": current_user_id,
            "request_id": req_id
        }
    )

    try:
        service = BloodRequestService(db)
        blood_request = await service.get_request(request_id)

        if not blood_request:
            logger.warning(
                "Blood request access failed - request not found",
                extra={
                    "event_type": "blood_request_not_found",
                    "current_user_id": current_user_id,
                    "request_id": req_id
                }
            )
            raise HTTPException(status_code=404, detail="Request not found")

        is_requester = blood_request.requester_id == current_user.id
        is_same_facility = (
            blood_request.facility_id == current_user.work_facility_id
            or (current_user.facility and blood_request.facility_id == current_user.facility.id)
        )

        if not is_requester and not is_same_facility:
            log_security_event(
                event_type="unauthorized_blood_request_access",
                details={
                    "reason": "not_authorized",
                    "request_id": req_id,
                    "is_requester": is_requester,
                    "is_same_facility": is_same_facility
                },
                user_id=current_user_id,
                ip_address=client_ip
            )

            logger.warning(
                "Blood request access denied - not authorized",
                extra={
                    "event_type": "blood_request_access_denied",
                    "current_user_id": current_user_id,
                    "request_id": req_id,
                    "reason": "not_authorized"
                }
            )

            raise HTTPException(status_code=403, detail="Not authorized to view this request")

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "Blood request access successful",
            extra={
                "event_type": "blood_request_accessed",
                "current_user_id": current_user_id,
                "request_id": req_id,
                "blood_type": blood_request.blood_type,
                "request_status": blood_request.request_status,
                "is_requester": is_requester,
                "duration_ms": duration_ms
            }
        )

        return BloodRequestResponse.from_orm_with_facility_names(blood_request)

    except HTTPException:
        raise
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Blood request access failed due to unexpected error",
            extra={
                "event_type": "blood_request_error",
                "current_user_id": current_user_id,
                "request_id": req_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )

        raise HTTPException(status_code=500, detail="Failed to retrieve blood request")


@router.patch("/{request_id}", response_model=BloodRequestResponse)
async def update_blood_request(
    request_id: UUID,
    update_data: BloodRequestUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_update"
    ))
):
    """Update a blood request"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    req_id = str(request_id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "Blood request update started",
        extra={
            "event_type": "blood_request_update_attempt",
            "current_user_id": current_user_id,
            "request_id": req_id,
            "update_fields": list(update_data.model_dump(exclude_unset=True).keys())
        }
    )
    
    try:
        service = BloodRequestService(db)
        
        # Verify ownership first
        blood_request = await service.get_request(request_id)
        if not blood_request:
            logger.warning(
                "Blood request update failed - request not found",
                extra={
                    "event_type": "blood_request_update_failed",
                    "current_user_id": current_user_id,
                    "request_id": req_id,
                    "reason": "not_found"
                }
            )
            raise HTTPException(status_code=404, detail="Request not found")
        
        if blood_request.requester_id != current_user.id:
            log_security_event(
                event_type="unauthorized_blood_request_update",
                details={
                    "reason": "not_owner",
                    "request_id": req_id,
                    "actual_owner": str(blood_request.requester_id)
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood request update denied - not authorized",
                extra={
                    "event_type": "blood_request_update_denied",
                    "current_user_id": current_user_id,
                    "request_id": req_id,
                    "reason": "not_owner"
                }
            )
            
            raise HTTPException(status_code=403, detail="Not authorized to update this request")
        
        # Store old values for audit
        old_values = {
            "request_status": blood_request.request_status,
            "processing_status": blood_request.processing_status,
            "priority": blood_request.priority,
            "notes": blood_request.notes
        }
        
        # Update request
        updated_request = await service.update_request(request_id, update_data)
        
        # Store new values for audit
        new_values = {
            "request_status": updated_request.request_status,
            "processing_status": updated_request.processing_status,
            "priority": updated_request.priority,
            "notes": updated_request.notes
        }
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Log successful update
        log_audit_event(
            action="update",
            resource_type="blood_request",
            resource_id=req_id,
            old_values=old_values,
            new_values=new_values,
            user_id=current_user_id
        )
        
        logger.info(
            "Blood request update successful",
            extra={
                "event_type": "blood_request_updated",
                "current_user_id": current_user_id,
                "request_id": req_id,
                "fields_updated": list(update_data.model_dump(exclude_unset=True).keys()),
                "new_status": updated_request.request_status,
                "duration_ms": duration_ms
            }
        )
        
        return updated_request
        
    except HTTPException:
        raise
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Blood request update failed due to unexpected error",
            extra={
                "event_type": "blood_request_update_error",
                "current_user_id": current_user_id,
                "request_id": req_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Blood request update failed")


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blood_request(
    request_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_delete"
    ))
):
    """Delete a blood request"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    req_id = str(request_id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "Blood request deletion started",
        extra={
            "event_type": "blood_request_deletion_attempt",
            "current_user_id": current_user_id,
            "request_id": req_id
        }
    )
    
    try:
        service = BloodRequestService(db)
        
        # Verify ownership first
        blood_request = await service.get_request(request_id)
        if not blood_request:
            logger.warning(
                "Blood request deletion failed - request not found",
                extra={
                    "event_type": "blood_request_deletion_failed",
                    "current_user_id": current_user_id,
                    "request_id": req_id,
                    "reason": "not_found"
                }
            )
            raise HTTPException(status_code=404, detail="Request not found")
        
        if blood_request.requester_id != current_user.id:
            log_security_event(
                event_type="unauthorized_blood_request_deletion",
                details={
                    "reason": "not_owner",
                    "request_id": req_id,
                    "actual_owner": str(blood_request.requester_id)
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood request deletion denied - not authorized",
                extra={
                    "event_type": "blood_request_deletion_denied",
                    "current_user_id": current_user_id,
                    "request_id": req_id,
                    "reason": "not_owner"
                }
            )
            
            raise HTTPException(status_code=403, detail="Not authorized to delete this request")
        
        # Store request data for audit before deletion
        request_data_for_audit = {
            "blood_type": blood_request.blood_type,
            "quantity": blood_request.quantity,
            "priority": blood_request.priority,
            "request_status": blood_request.request_status,
            "processing_status": blood_request.processing_status
        }
        
        # Delete request
        await service.delete_request(request_id)
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Log successful deletion
        log_audit_event(
            action="delete",
            resource_type="blood_request",
            resource_id=req_id,
            old_values=request_data_for_audit,
            new_values=None,
            user_id=current_user_id
        )
        
        log_security_event(
            event_type="blood_request_deleted",
            details={
                "blood_type": blood_request.blood_type,
                "quantity": blood_request.quantity,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )
        
        logger.info(
            "Blood request deletion successful",
            extra={
                "event_type": "blood_request_deleted",
                "current_user_id": current_user_id,
                "request_id": req_id,
                "blood_type": blood_request.blood_type,
                "duration_ms": duration_ms
            }
        )
        
        return {"detail": "Blood request deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Blood request deletion failed due to unexpected error",
            extra={
                "event_type": "blood_request_deletion_error",
                "current_user_id": current_user_id,
                "request_id": req_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Blood request deletion failed")


@router.get("/status/{status}", response_model=List[BloodRequestResponse])
async def list_requests_by_status(
    status: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    ))
):
    """List requests by status for the current user."""
    start_time = time.time()
    current_user_id = str(current_user.id)
    
    logger.info(
        "Requests by status access",
        extra={
            "event_type": "requests_by_status_access",
            "current_user_id": current_user_id,
            "status": status
        }
    )
    
    try:
        # Validate status
        try:
            request_status = RequestStatus(status)
        except ValueError:
            logger.warning(
                "Requests by status failed - invalid status",
                extra={
                    "event_type": "requests_by_status_failed",
                    "current_user_id": current_user_id,
                    "invalid_status": status,
                    "reason": "invalid_status"
                }
            )
            raise HTTPException(status_code=400, detail="Invalid request status")
        
        service = BloodRequestService(db)
        
        # Get all requests by status, then filter by user
        all_requests = await service.list_requests_by_status(request_status)
        user_requests = [req for req in all_requests if req.requester_id == current_user.id]
        
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "Requests by status access successful",
            extra={
                "event_type": "requests_by_status_accessed",
                "current_user_id": current_user_id,
                "status": status,
                "request_count": len(user_requests),
                "total_matching_status": len(all_requests),
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow queries
        if duration_ms > 1000:  # More than 1 second
            log_performance_metric(
                operation="get_requests_by_status",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_query": True,
                    "status_filter": status,
                    "user_results": len(user_requests),
                    "total_results": len(all_requests)
                }
            )
        
        return user_requests
        
    except HTTPException:
        raise
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Requests by status access failed due to unexpected error",
            extra={
                "event_type": "requests_by_status_error",
                "current_user_id": current_user_id,
                "status": status,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve requests by status")


# Routes for facility managers/staff
@router.get("/facility/{facility_id}/requests", response_model=List[BloodRequestResponse])
async def list_facility_requests_by_id(
    facility_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage"
    ))
):
    """List all requests for a specific facility."""
    start_time = time.time()
    current_user_id = str(current_user.id)
    fac_id = str(facility_id)
    
    logger.info(
        "Facility requests by ID access",
        extra={
            "event_type": "facility_requests_by_id_access",
            "current_user_id": current_user_id,
            "facility_id": fac_id
        }
    )
    
    try:
        service = BloodRequestService(db)
        requests = await service.list_requests_by_facility(facility_id)
        
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(
            "Facility requests by ID access successful",
            extra={
                "event_type": "facility_requests_by_id_accessed",
                "current_user_id": current_user_id,
                "facility_id": fac_id,
                "request_count": len(requests),
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow queries
        if duration_ms > 1500:  # More than 1.5 seconds
            log_performance_metric(
                operation="get_facility_requests_by_id",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_query": True,
                    "facility_id": fac_id,
                    "result_count": len(requests)
                }
            )
        
        return requests
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Facility requests by ID access failed due to unexpected error",
            extra={
                "event_type": "facility_requests_by_id_error",
                "current_user_id": current_user_id,
                "facility_id": fac_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve facility requests")


@router.patch("/facility/{request_id}/respond", response_model=BloodRequestResponse)
async def respond_to_request(
    request_id: UUID,
    response_data: BloodRequestStatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_update"
    ))
):
    """Allow facility staff to respond to a blood request"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    req_id = str(request_id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "Request response started",
        extra={
            "event_type": "request_response_attempt",
            "current_user_id": current_user_id,
            "request_id": req_id,
            "new_status": response_data.request_status.value if response_data.request_status else None,
            "responder_role": "facility_staff"
        }
    )
    
    try:
        service = BloodRequestService(db)
        
        # Get the request first
        blood_request = await service.get_request(request_id)
        if not blood_request:
            logger.warning(
                "Request response failed - request not found",
                extra={
                    "event_type": "request_response_failed",
                    "current_user_id": current_user_id,
                    "request_id": req_id,
                    "reason": "not_found"
                }
            )
            raise HTTPException(status_code=404, detail="Request not found")
        
        # Store old values for audit
        old_values = {
            "request_status": blood_request.request_status,
            "processing_status": blood_request.processing_status,
            "fulfilled_by_id": str(blood_request.fulfilled_by_id) if blood_request.fulfilled_by_id else None,
            "notes": blood_request.notes
        }
        
        # Set the fulfilled_by field if status is being set to accepted
        if response_data.request_status == RequestStatus.accepted:
            response_data = response_data.model_copy(update={"fulfilled_by_id": current_user.id})
        
        updated_request = await service.update_request(request_id, response_data)
        
        # Store new values for audit
        new_values = {
            "request_status": updated_request.request_status,
            "processing_status": updated_request.processing_status,
            "fulfilled_by_id": str(updated_request.fulfilled_by_id) if updated_request.fulfilled_by_id else None,
            "notes": updated_request.notes
        }
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Log successful response
        log_audit_event(
            action="respond",
            resource_type="blood_request",
            resource_id=req_id,
            old_values=old_values,
            new_values=new_values,
            user_id=current_user_id
        )
        
        log_security_event(
            event_type="blood_request_response",
            details={
                "request_id": req_id,
                "old_status": old_values["request_status"],
                "new_status": updated_request.request_status,
                "blood_type": updated_request.blood_type,
                "quantity": updated_request.quantity_requested,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )
        
        logger.info(
            "Request response successful",
            extra={
                "event_type": "request_responded",
                "current_user_id": current_user_id,
                "request_id": req_id,
                "old_status": old_values["request_status"],
                "new_status": updated_request.request_status,
                "blood_type": updated_request.blood_type,
                "is_accepted": response_data.request_status == RequestStatus.accepted,
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow operations
        if duration_ms > 2000:  # More than 2 seconds
            log_performance_metric(
                operation="respond_to_request",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_operation": True,
                    "status_change": f"{old_values['request_status']} -> {updated_request.request_status}",
                    "blood_type": updated_request.blood_type
                }
            )
        
        # Convert to response model properly
        return BloodRequestResponse.from_orm_with_facility_names(updated_request)
        
    except HTTPException:
        raise
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Request response failed due to unexpected error",
            extra={
                "event_type": "request_response_error",
                "current_user_id": current_user_id,
                "request_id": req_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        log_security_event(
            event_type="request_response_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "request_id": req_id,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )

        raise HTTPException(status_code=500, detail="Failed to respond to request")


@router.patch("/{request_id}/cancel", response_model=BloodRequestResponse)
async def cancel_blood_request(
    request_id: UUID,
    request: Request,
    cancellation_reason: Optional[str] = Query(None, description="Reason for cancelling the request"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_update"
    ))
):
    """Cancel a blood request - only pending requests can be cancelled"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    req_id = str(request_id)
    client_ip = get_client_ip(request)
    
    logger.info(
        "Blood request cancellation started",
        extra={
            "event_type": "blood_request_cancellation_attempt",
            "current_user_id": current_user_id,
            "request_id": req_id,
            "cancellation_reason": cancellation_reason
        }
    )
    
    try:
        service = BloodRequestService(db)
        
        # Get the request first to verify ownership and status
        blood_request = await service.get_request(request_id)
        if not blood_request:
            logger.warning(
                "Blood request cancellation failed - request not found",
                extra={
                    "event_type": "blood_request_cancellation_failed",
                    "current_user_id": current_user_id,
                    "request_id": req_id,
                    "reason": "not_found"
                }
            )
            raise HTTPException(status_code=404, detail="Request not found")
        
        # Verify ownership
        if blood_request.requester_id != current_user.id:
            log_security_event(
                event_type="unauthorized_blood_request_cancellation",
                details={
                    "reason": "not_owner",
                    "request_id": req_id,
                    "actual_owner": str(blood_request.requester_id)
                },
                user_id=current_user_id,
                ip_address=client_ip
            )
            
            logger.warning(
                "Blood request cancellation denied - not authorized",
                extra={
                    "event_type": "blood_request_cancellation_denied",
                    "current_user_id": current_user_id,
                    "request_id": req_id,
                    "reason": "not_owner"
                }
            )
            
            raise HTTPException(status_code=403, detail="Not authorized to cancel this request")
        
        # Check if request is in a cancellable state
        if blood_request.request_status != RequestStatus.pending:
            logger.warning(
                "Blood request cancellation failed - invalid status",
                extra={
                    "event_type": "blood_request_cancellation_failed",
                    "current_user_id": current_user_id,
                    "request_id": req_id,
                    "current_status": blood_request.request_status.value,
                    "reason": "invalid_status"
                }
            )
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot cancel request with status '{blood_request.request_status.value}'. Only pending requests can be cancelled."
            )
        
        # Store old values for audit
        old_values = {
            "request_status": blood_request.request_status.value,
            "cancellation_reason": blood_request.cancellation_reason,
            "blood_type": blood_request.blood_type,
            "quantity": blood_request.quantity_requested,
            "priority": blood_request.priority
        }
        
        # Cancel the request
        cancelled_request = await service.cancel_request(
            request_id=request_id,
            cancellation_reason=cancellation_reason,
            user_id=current_user.id
        )
        
        # Store new values for audit
        new_values = {
            "request_status": cancelled_request.request_status.value,
            "cancellation_reason": cancelled_request.cancellation_reason,
            "blood_type": cancelled_request.blood_type,
            "quantity": cancelled_request.quantity_requested,
            "priority": cancelled_request.priority
        }
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Log successful cancellation
        log_audit_event(
            action="cancel",
            resource_type="blood_request",
            resource_id=req_id,
            old_values=old_values,
            new_values=new_values,
            user_id=current_user_id
        )
        
        log_security_event(
            event_type="blood_request_cancelled",
            details={
                "blood_type": cancelled_request.blood_type,
                "quantity": cancelled_request.quantity_requested,
                "cancellation_reason": cancelled_request.cancellation_reason,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )
        
        logger.info(
            "Blood request cancellation successful",
            extra={
                "event_type": "blood_request_cancelled",
                "current_user_id": current_user_id,
                "request_id": req_id,
                "blood_type": cancelled_request.blood_type,
                "quantity": cancelled_request.quantity_requested,
                "cancellation_reason": cancelled_request.cancellation_reason,
                "duration_ms": duration_ms
            }
        )
        
        # Log performance metric for slow operations
        if duration_ms > 2000:  # More than 2 seconds
            log_performance_metric(
                operation="cancel_blood_request",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_operation": True,
                    "blood_type": cancelled_request.blood_type,
                    "cancellation_reason": cancellation_reason
                }
            )
        
        # Return the cancelled request using the established pattern
        return BloodRequestResponse.from_orm_with_facility_names(cancelled_request)
        
    except HTTPException:
        raise
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "Blood request cancellation failed due to unexpected error",
            extra={
                "event_type": "blood_request_cancellation_error",
                "current_user_id": current_user_id,
                "request_id": req_id,
                "error": str(e),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        
        log_security_event(
            event_type="blood_request_cancellation_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "request_id": req_id,
                "duration_ms": duration_ms
            },
            user_id=current_user_id,
            ip_address=client_ip
        )
        
        raise HTTPException(status_code=500, detail="Blood request cancellation failed")