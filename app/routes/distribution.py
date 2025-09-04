from app.models.health_facility import Facility
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_
from app.schemas.distribution import (
    BloodDistributionCreate,
    BloodDistributionResponse,
    BloodDistributionUpdate,
    BloodDistributionDetailResponse,
    DistributionStatus,
)
from app.services.distribution import BloodDistributionService
from app.models.user import User
from app.models.blood_bank import BloodBank
# from app.models.distribution import BloodDistributionStatus
from app.utils.permission_checker import require_permission
from app.utils.ip_address_finder import get_client_ip
from app.dependencies import get_db
from app.utils.logging_config import (
    get_logger,
    log_audit_event,
    log_security_event,
    log_performance_metric,
)
from uuid import UUID
from typing import List, Optional
from datetime import datetime
import time

logger = get_logger(__name__)

router = APIRouter(prefix="/blood-distribution", tags=["blood distribution"])


# Helper function to get blood bank ID for the current user
async def get_user_blood_bank_id(db: AsyncSession, user_id: UUID) -> UUID:
    """Get the blood bank ID associated with the user"""

    result = await db.execute(
        select(BloodBank).where(
            or_(
                # Case 1: User is the blood bank manager
                BloodBank.manager_id == user_id,
                # Case 2: User is staff working in the facility
                BloodBank.facility_id
                == (
                    select(User.work_facility_id)
                    .where(User.id == user_id)
                    .scalar_subquery()
                ),
                # Case 3: User is the facility manager
                BloodBank.facility_id
                == (
                    select(Facility.id)
                    .where(Facility.facility_manager_id == user_id)
                    .scalar_subquery()
                ),
            )
        )
    )

    blood_bank = result.scalar_one_or_none()

    if blood_bank:
        return blood_bank.id

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You are not associated with any blood bank",
    )


@router.post(
    "/",
    response_model=BloodDistributionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_distribution(
    distribution_data: BloodDistributionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.issue.can_create"
        )
    ),
):
    """Create a new blood distribution"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    client_ip = get_client_ip(request)

    logger.info(
        "Blood distribution creation started",
        extra={
            "event_type": "distribution_creation_attempt",
            "user_id": current_user_id,
            "client_ip": client_ip,
            "blood_product": distribution_data.blood_product,
            "blood_type": distribution_data.blood_type,
            "quantity": distribution_data.quantity,
            "dispatched_to_id": str(distribution_data.dispatched_to_id),
        },
    )

    try:
        # Get the blood bank associated with the user
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)

        # Get the facility ID associated with this blood bank to prevent self-distribution
        result = await db.execute(
            select(BloodBank).where(BloodBank.id == blood_bank_id)
        )
        blood_bank = result.scalar_one()

        # Check if the destination facility is the same as the source blood bank's facility
        if blood_bank.facility_id == distribution_data.dispatched_to_id:
            log_security_event(
                event_type="distribution_creation_denied",
                details={
                    "reason": "self_distribution_attempt",
                    "facility_id": str(blood_bank.facility_id),
                    "blood_bank_id": str(blood_bank_id),
                },
                user_id=current_user_id,
                ip_address=client_ip,
            )

            logger.warning(
                "Distribution creation denied - self-distribution attempt",
                extra={
                    "event_type": "distribution_creation_denied",
                    "user_id": current_user_id,
                    "reason": "self_distribution_attempt",
                    "facility_id": str(blood_bank.facility_id),
                },
            )

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot distribute blood to your own facility",
            )

        distribution_service = BloodDistributionService(db)
        new_distribution = await distribution_service.create_distribution(
            distribution_data=distribution_data,
            blood_bank_id=blood_bank_id,
            created_by_id=current_user.id,
        )

        # Commit the transaction since we removed the transaction context in the service
        await db.commit()

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful creation
        log_security_event(
            event_type="distribution_created",
            details={
                "distribution_id": str(new_distribution.id),
                "blood_product": distribution_data.blood_product,
                "blood_type": distribution_data.blood_type,
                "quantity": distribution_data.quantity,
                "dispatched_from_id": str(blood_bank_id),
                "dispatched_to_id": str(distribution_data.dispatched_to_id),
                "duration_ms": duration_ms,
            },
            user_id=current_user_id,
            ip_address=client_ip,
        )

        log_audit_event(
            action="create",
            resource_type="blood_distribution",
            resource_id=str(new_distribution.id),
            new_values={
                "blood_product": distribution_data.blood_product,
                "blood_type": distribution_data.blood_type,
                "quantity": distribution_data.quantity,
                "dispatched_from_id": str(blood_bank_id),
                "dispatched_to_id": str(distribution_data.dispatched_to_id),
                "status": new_distribution.status.value,
                "created_by_id": current_user_id,
            },
            user_id=current_user_id,
        )

        logger.info(
            "Blood distribution creation successful",
            extra={
                "event_type": "distribution_created",
                "user_id": current_user_id,
                "distribution_id": str(new_distribution.id),
                "blood_product": distribution_data.blood_product,
                "blood_type": distribution_data.blood_type,
                "quantity": distribution_data.quantity,
                "duration_ms": duration_ms,
            },
        )

        # Log performance metric for slow operations
        if duration_ms > 2000:  # More than 2 seconds
            log_performance_metric(
                operation="distribution_creation",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_operation": True,
                    "blood_product": distribution_data.blood_product,
                    "quantity": distribution_data.quantity,
                },
            )

        # Format the response with additional information
        response = BloodDistributionDetailResponse(
            **BloodDistributionResponse.model_validate(
                new_distribution, from_attributes=True
            ).model_dump(),
            dispatched_from_name=(
                new_distribution.dispatched_from.blood_bank_name
                if new_distribution.dispatched_from
                else None
            ),
            dispatched_to_name=(
                new_distribution.dispatched_to.facility_name
                if new_distribution.dispatched_to
                else None
            ),
            created_by_name=(
                new_distribution.created_by.last_name
                if new_distribution.created_by
                else None
            )
        )

        return response

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000
        dispatched_to_id = (
            str(distribution_data.dispatched_to_id)
            if "distribution" in locals() and distribution_data
            else "unknown"
        )

        logger.error(
            "Distribution creation failed due to unexpected error",
            extra={
                "event_type": "distribution_creation_error",
                "user_id": current_user_id,
                "dispatched_to_id": dispatched_to_id,
                "error": str(e),
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )
        log_security_event(
            event_type="distribution_creation_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "duration_ms": duration_ms,
            },
            user_id=current_user_id,
            ip_address=client_ip,
        )
        raise HTTPException(status_code=500, detail="Distribution creation failed")


@router.get(
    "/facility/{facility_id}", response_model=List[BloodDistributionDetailResponse]
)
async def get_distributions_by_facility(
    facility_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.issue.can_view"
        )
    ),
):
    """Get all blood distributions for a specific facility with comprehensive logging"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    facility_id_str = str(facility_id)
    client_ip = get_client_ip(request)

    logger.info(
        "Facility distributions retrieval started",
        extra={
            "event_type": "facility_distributions_attempt",
            "user_id": current_user_id,
            "facility_id": facility_id_str,
            "client_ip": client_ip,
        },
    )

    try:
        # Get the blood bank associated with the user
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)

        distribution_service = BloodDistributionService(db)
        all_distributions = await distribution_service.get_distributions_by_facility(
            facility_id
        )

        # Filter to only include distributions from this user's blood bank
        user_distributions = [
            dist
            for dist in all_distributions
            if dist.dispatched_from_id == blood_bank_id
        ]

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "Facility distributions retrieval successful",
            extra={
                "event_type": "facility_distributions_retrieved",
                "user_id": current_user_id,
                "facility_id": facility_id_str,
                "blood_bank_id": str(blood_bank_id),
                "total_distributions": len(all_distributions),
                "user_distributions": len(user_distributions),
                "duration_ms": duration_ms,
            },
        )

        # Log performance metric for slow queries
        if duration_ms > 800:  # More than 800ms
            log_performance_metric(
                operation="facility_distributions_retrieval",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_query": True,
                    "facility_id": facility_id_str,
                    "result_count": len(user_distributions),
                    "blood_bank_id": str(blood_bank_id),
                },
            )

        # Format response
        response_data = [
            BloodDistributionDetailResponse(
                **BloodDistributionResponse.model_validate(
                    dist, from_attributes=True
                ).model_dump(),
                dispatched_from_name=(
                    dist.dispatched_from.blood_bank_name
                    if dist.dispatched_from
                    else None
                ),
                dispatched_to_name=(
                    dist.dispatched_to.facility_name if dist.dispatched_to else None
                ),
                created_by_name=dist.created_by.last_name if dist.created_by else None
            )
            for dist in user_distributions
        ]

        return response_data

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Facility distributions retrieval failed due to unexpected error",
            extra={
                "event_type": "facility_distributions_error",
                "user_id": current_user_id,
                "facility_id": facility_id_str,
                "error": str(e),
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )

        raise HTTPException(
            status_code=500, detail="Failed to retrieve facility distributions"
        )


@router.get("/{distribution_id}", response_model=BloodDistributionDetailResponse)
async def get_distribution(
    distribution_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.issue.can_view"
        )
    ),
):
    """Get details of a specific blood distribution with logging"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    distribution_id_str = str(distribution_id)
    client_ip = get_client_ip(request)

    logger.info(
        "Distribution retrieval started",
        extra={
            "event_type": "distribution_retrieval_attempt",
            "user_id": current_user_id,
            "distribution_id": distribution_id_str,
            "client_ip": client_ip,
        },
    )

    try:
        distribution_service = BloodDistributionService(db)
        distribution = await distribution_service.get_distribution(distribution_id)

        if not distribution:
            logger.warning(
                "Distribution retrieval failed - not found",
                extra={
                    "event_type": "distribution_retrieval_failed",
                    "user_id": current_user_id,
                    "distribution_id": distribution_id_str,
                    "reason": "not_found",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blood distribution not found",
            )

        # Authorization check: user must be associated with either the sending blood bank or receiving facility
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)

        # Restrict access to dispatching or receiving blood bank
        if (
            distribution.dispatched_from_id != blood_bank_id
            and distribution.dispatched_to_id != blood_bank_id
        ):
            log_security_event(
                event_type="distribution_access_denied",
                details={
                    "reason": "insufficient_permissions",
                    "distribution_id": distribution_id_str,
                    "user_blood_bank_id": str(blood_bank_id),
                    "distribution_from_id": str(distribution.dispatched_from_id),
                },
                user_id=current_user_id,
                ip_address=client_ip,
            )

            logger.warning(
                "Distribution access denied - insufficient permissions",
                extra={
                    "event_type": "distribution_access_denied",
                    "user_id": current_user_id,
                    "distribution_id": distribution_id_str,
                    "reason": "insufficient_permissions",
                },
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view this distribution",
            )

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "Distribution retrieval successful",
            extra={
                "event_type": "distribution_retrieved",
                "user_id": current_user_id,
                "distribution_id": distribution_id_str,
                "blood_product": distribution.blood_product,
                "blood_type": distribution.blood_type,
                "status": distribution.status.value,
                "duration_ms": duration_ms,
            },
        )

        # Format response with additional information
        response = BloodDistributionDetailResponse(
            **BloodDistributionResponse.model_validate(
                distribution, from_attributes=True
            ).model_dump(),
            dispatched_from_name=(
                distribution.dispatched_from.blood_bank_name
                if distribution.dispatched_from
                else None
            ),
            dispatched_to_name=(
                distribution.dispatched_to.facility_name
                if distribution.dispatched_to
                else None
            ),
            created_by_name=(
                distribution.created_by.last_name if distribution.created_by else None
            )
        )

        return response

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Distribution retrieval failed due to unexpected error",
            extra={
                "event_type": "distribution_retrieval_error",
                "user_id": current_user_id,
                "distribution_id": distribution_id_str,
                "error": str(e),
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="Failed to retrieve distribution")


@router.get("/", response_model=List[BloodDistributionDetailResponse])
async def list_distributions(
    status: Optional[DistributionStatus] = None,
    facility_id: Optional[UUID] = None,
    recent_days: Optional[int] = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.issue.can_view"
        )
    ),
):
    """List blood distributions with optional filtering and comprehensive logging"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    client_ip = get_client_ip(request) if request else "unknown"

    logger.info(
        "Distribution list retrieval started",
        extra={
            "event_type": "distribution_list_attempt",
            "user_id": current_user_id,
            "client_ip": client_ip,
            "filters": {
                "status": status.value if status else None,
                "facility_id": str(facility_id) if facility_id else None,
                "recent_days": recent_days,
            },
        },
    )

    try:
        # Get the blood bank associated with the user
        blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
        if not blood_bank_id:
            log_security_event(
                event_type="distribution_list_access_denied",
                details={
                    "reason": "no_blood_bank_association",
                },
                user_id=current_user_id,
                ip_address=client_ip,
            )

            logger.warning(
                "Distribution list access denied - no blood bank association",
                extra={
                    "event_type": "distribution_list_access_denied",
                    "user_id": current_user_id,
                    "reason": "no_blood_bank_association",
                },
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not associated with any blood bank",
            )

        distribution_service = BloodDistributionService(db)

        # Get all distributions for this blood bank first
        blood_bank_distributions = (
            await distribution_service.get_distributions_by_blood_bank(blood_bank_id)
        )

        # Apply additional filters if specified
        if status:
            enum_status = DistributionStatus(status)
            filtered_distributions = [
                d for d in blood_bank_distributions if d.status == enum_status
            ]
        elif facility_id:
            filtered_distributions = [
                d for d in blood_bank_distributions if d.dispatched_to_id == facility_id
            ]
        elif recent_days:
            cutoff_date = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            cutoff_date = cutoff_date.replace(day=cutoff_date.day - recent_days)
            filtered_distributions = [
                d for d in blood_bank_distributions if d.created_at >= cutoff_date
            ]
        else:
            filtered_distributions = blood_bank_distributions

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "Distribution list retrieval successful",
            extra={
                "event_type": "distribution_list_retrieved",
                "user_id": current_user_id,
                "blood_bank_id": str(blood_bank_id),
                "total_distributions": len(blood_bank_distributions),
                "filtered_distributions": len(filtered_distributions),
                "duration_ms": duration_ms,
            },
        )

        # Log performance metric for slow queries
        if duration_ms > 1000:  # More than 1 second
            log_performance_metric(
                operation="distribution_list_retrieval",
                duration_seconds=duration_ms / 1000,
                additional_metrics={
                    "slow_query": True,
                    "result_count": len(filtered_distributions),
                    "blood_bank_id": str(blood_bank_id),
                    "filters_applied": bool(status or facility_id or recent_days),
                },
            )

        # Format each distribution for response
        response_data = [
            BloodDistributionDetailResponse(
                **BloodDistributionResponse.model_validate(
                    dist, from_attributes=True
                ).model_dump(),
                dispatched_from_name=(
                    dist.dispatched_from.blood_bank_name
                    if dist.dispatched_from
                    else None
                ),
                dispatched_to_name=(
                    dist.dispatched_to.facility_name if dist.dispatched_to else None
                ),
                created_by_name=dist.created_by.last_name if dist.created_by else None
            )
            for dist in filtered_distributions
        ]

        return response_data

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Distribution list retrieval failed due to unexpected error",
            extra={
                "event_type": "distribution_list_error",
                "user_id": current_user_id,
                "error": str(e),
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="Failed to retrieve distributions")


@router.patch("/{distribution_id}", response_model=BloodDistributionDetailResponse)
async def update_distribution(
    distribution_id: UUID,
    distribution_data: BloodDistributionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.issue.can_update"
        )
    ),
):
    """Update a blood distribution with comprehensive logging"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    distribution_id_str = str(distribution_id)
    client_ip = get_client_ip(request)

    logger.info(
        "Distribution update started",
        extra={
            "event_type": "distribution_update_attempt",
            "user_id": current_user_id,
            "distribution_id": distribution_id_str,
            "client_ip": client_ip,
            "update_fields": list(
                distribution_data.model_dump(exclude_unset=True).keys()
            ),
        },
    )

    try:
        distribution_service = BloodDistributionService(db)
        distribution = await distribution_service.get_distribution(distribution_id)

        if not distribution:
            logger.warning(
                "Distribution update failed - not found",
                extra={
                    "event_type": "distribution_update_failed",
                    "user_id": current_user_id,
                    "distribution_id": distribution_id_str,
                    "reason": "not_found",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blood distribution not found",
            )

        # Check if user is associated with this blood bank
        user_blood_bank_id = await get_user_blood_bank_id(db, current_user.id)

        if distribution.dispatched_from_id != user_blood_bank_id:
            log_security_event(
                event_type="distribution_update_denied",
                details={
                    "reason": "insufficient_permissions",
                    "distribution_id": distribution_id_str,
                    "user_blood_bank_id": str(user_blood_bank_id),
                    "distribution_from_id": str(distribution.dispatched_from_id),
                },
                user_id=current_user_id,
                ip_address=client_ip,
            )

            logger.warning(
                "Distribution update denied - insufficient permissions",
                extra={
                    "event_type": "distribution_update_denied",
                    "user_id": current_user_id,
                    "distribution_id": distribution_id_str,
                    "reason": "insufficient_permissions",
                },
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update this distribution",
            )

        # Store old values for audit
        old_values = {
            "blood_product": distribution.blood_product,
            "blood_type": distribution.blood_type,
            "quantity": distribution.quantity,
            "status": distribution.status.value,
            "notes": distribution.notes,
            "tracking_number": distribution.tracking_number,
        }

        # Convert string status to enum if present
        if distribution_data.status:
            # The enum value is already handled by Pydantic conversion
            pass

        updated_distribution = await distribution_service.update_distribution(
            distribution_id, distribution_data
        )

        # Store new values for audit
        new_values = {
            "blood_product": updated_distribution.blood_product,
            "blood_type": updated_distribution.blood_type,
            "quantity": updated_distribution.quantity,
            "status": updated_distribution.status.value,
            "notes": updated_distribution.notes,
            "tracking_number": updated_distribution.tracking_number,
        }

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful update
        log_audit_event(
            action="update",
            resource_type="blood_distribution",
            resource_id=distribution_id_str,
            old_values=old_values,
            new_values=new_values,
            user_id=current_user_id,
        )

        logger.info(
            "Distribution update successful",
            extra={
                "event_type": "distribution_updated",
                "user_id": current_user_id,
                "distribution_id": distribution_id_str,
                "fields_updated": list(
                    distribution_data.model_dump(exclude_unset=True).keys()
                ),
                "old_status": old_values.get("status"),
                "new_status": new_values.get("status"),
                "duration_ms": duration_ms,
            },
        )

        # Log security event for status changes
        if distribution_data.status and old_values.get("status") != new_values.get(
            "status"
        ):
            log_security_event(
                event_type="distribution_status_changed",
                details={
                    "distribution_id": distribution_id_str,
                    "old_status": old_values.get("status"),
                    "new_status": new_values.get("status"),
                    "duration_ms": duration_ms,
                },
                user_id=current_user_id,
                ip_address=client_ip,
            )

        # Format response
        response = BloodDistributionDetailResponse(
            **BloodDistributionResponse.model_validate(
                updated_distribution, from_attributes=True
            ).model_dump(),
            dispatched_from_name=(
                updated_distribution.dispatched_from.blood_bank_name
                if updated_distribution.dispatched_from
                else None
            ),
            dispatched_to_name=(
                updated_distribution.dispatched_to.facility_name
                if updated_distribution.dispatched_to
                else None
            ),
            created_by_name=(
                updated_distribution.created_by.last_name
                if updated_distribution.created_by
                else None
            )
        )

        return response

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Distribution update failed due to unexpected error",
            extra={
                "event_type": "distribution_update_error",
                "user_id": current_user_id,
                "distribution_id": distribution_id_str,
                "error": str(e),
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )

        raise HTTPException(status_code=500, detail="Distribution update failed")


@router.delete("/{distribution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_distribution(
    distribution_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.issue.can_delete"
        )
    ),
):
    """Delete a blood distribution with comprehensive logging"""
    start_time = time.time()
    current_user_id = str(current_user.id)
    distribution_id_str = str(distribution_id)
    client_ip = get_client_ip(request)

    logger.info(
        "Distribution deletion started",
        extra={
            "event_type": "distribution_deletion_attempt",
            "user_id": current_user_id,
            "distribution_id": distribution_id_str,
            "client_ip": client_ip,
        },
    )

    try:
        distribution_service = BloodDistributionService(db)
        distribution = await distribution_service.get_distribution(distribution_id)

        if not distribution:
            logger.warning(
                "Distribution deletion failed - not found",
                extra={
                    "event_type": "distribution_deletion_failed",
                    "user_id": current_user_id,
                    "distribution_id": distribution_id_str,
                    "reason": "not_found",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Blood distribution not found",
            )

        # Check if user is associated with this blood bank
        user_blood_bank_id = await get_user_blood_bank_id(db, current_user.id)

        if distribution.dispatched_from_id != user_blood_bank_id:
            log_security_event(
                event_type="distribution_deletion_denied",
                details={
                    "reason": "insufficient_permissions",
                    "distribution_id": distribution_id_str,
                    "user_blood_bank_id": str(user_blood_bank_id),
                    "distribution_from_id": str(distribution.dispatched_from_id),
                },
                user_id=current_user_id,
                ip_address=client_ip,
            )

            logger.warning(
                "Distribution deletion denied - insufficient permissions",
                extra={
                    "event_type": "distribution_deletion_denied",
                    "user_id": current_user_id,
                    "distribution_id": distribution_id_str,
                    "reason": "insufficient_permissions",
                },
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this distribution",
            )

        # Store distribution data for audit before deletion
        distribution_data_for_audit = {
            "blood_product": distribution.blood_product,
            "blood_type": distribution.blood_type,
            "quantity": distribution.quantity,
            "status": distribution.status.value,
            "dispatched_from_id": str(distribution.dispatched_from_id),
            "dispatched_to_id": str(distribution.dispatched_to_id),
            "created_by_id": (
                str(distribution.created_by_id) if distribution.created_by_id else None
            ),
        }

        await distribution_service.delete_distribution(distribution_id)

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log successful deletion
        log_security_event(
            event_type="distribution_deleted",
            details={
                "distribution_id": distribution_id_str,
                "blood_product": distribution.blood_product,
                "blood_type": distribution.blood_type,
                "quantity": distribution.quantity,
                "duration_ms": duration_ms,
            },
            user_id=current_user_id,
            ip_address=client_ip,
        )

        log_audit_event(
            action="delete",
            resource_type="blood_distribution",
            resource_id=distribution_id_str,
            old_values=distribution_data_for_audit,
            new_values=None,
            user_id=current_user_id,
        )

        logger.info(
            "Distribution deletion successful",
            extra={
                "event_type": "distribution_deleted",
                "user_id": current_user_id,
                "distribution_id": distribution_id_str,
                "blood_product": distribution.blood_product,
                "blood_type": distribution.blood_type,
                "duration_ms": duration_ms,
            },
        )

        return {"detail": "Blood distribution deleted successfully"}

    except HTTPException:
        # Re-raise HTTP exceptions (already logged above)
        raise
    except Exception as e:
        # Log unexpected errors
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Distribution deletion failed due to unexpected error",
            extra={
                "event_type": "distribution_deletion_error",
                "user_id": current_user_id,
                "distribution_id": distribution_id_str,
                "error": str(e),
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )
        log_security_event(
            event_type="distribution_deletion_error",
            details={
                "reason": "unexpected_error",
                "error": str(e),
                "duration_ms": duration_ms,
            },
            user_id=current_user_id,
            ip_address=client_ip,
        )
        raise HTTPException(status_code=500, detail="Distribution deletion failed")
