from fastapi import APIRouter, Depends, HTTPException, status, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.tracking_schema import (
    TrackStateCreate,
    TrackStateResponse,
    TrackStateDetailResponse,
)
from app.services.tracking_service import TrackStateService
from app.models.user_model import User
from app.dependencies import get_db
from app.utils.permission_checker import require_permission, require_role
from app.utils.logging_config import (
    get_logger,
    log_audit_event,
    log_security_event,
    LogContext,
)
from uuid import UUID
from typing import List

# Initialize logger
logger = get_logger(__name__)

router = APIRouter(prefix="/track-states", tags=["track states"])

# NOTE: To avoid greenlet_spawn errors, ensure that all relationships (e.g., created_by)
# are eagerly loaded in your TrackStateService methods using selectinload or joinedload.
# Do NOT access relationship attributes unless they are already loaded.


@router.post(
    "/", response_model=TrackStateDetailResponse, status_code=status.HTTP_201_CREATED
)
async def create_track_state(
    track_data: TrackStateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "blood.distribution.can_manage",
            "blood.inventory.can_manage",
            "blood.tracking.can_create",
        )
    ),
    request: Request = None,
):
    """
    Create a new tracking state for a blood distribution.
    Requires appropriate permissions for blood distribution or inventory management.
    """
    # Set up logging context
    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        logger.info(
            "Track state creation initiated",
            extra={
                "event_type": "track_state_creation_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "blood_request_id": str(track_data.blood_request_id),
                "blood_distribution_id": (
                    str(track_data.blood_distribution_id)
                    if track_data.blood_distribution_id
                    else None
                ),
                "status": track_data.status,
                "location": track_data.location,
            },
        )

        try:
            track_service = TrackStateService(db)

            # Ensure this is awaited and the service method is async
            new_track = await track_service.create_track_state(
                track_data, current_user.id
            )

            # Log audit event for track state creation
            log_audit_event(
                action="create",
                resource_type="track_state",
                resource_id=str(new_track.id),
                new_values={
                    "status": new_track.status,
                    "location": new_track.location,
                    "notes": new_track.notes,
                    "blood_request_id": str(new_track.blood_request_id),
                    "blood_distribution_id": (
                        str(new_track.blood_distribution_id)
                        if new_track.blood_distribution_id
                        else None
                    ),
                },
                user_id=str(current_user.id),
            )

            # Format the response with additional details
            response = TrackStateDetailResponse(
                **TrackStateResponse.model_validate(
                    new_track, from_attributes=True
                ).model_dump(),
                created_by_name=getattr(new_track, "created_by_name", None),
            )

            logger.info(
                "Track state created successfully",
                extra={
                    "event_type": "track_state_created",
                    "track_state_id": str(new_track.id),
                    "user_id": str(current_user.id),
                    "status": new_track.status,
                    "blood_request_id": str(new_track.blood_request_id),
                },
            )

            return response

        except HTTPException:
            # Re-raise HTTP exceptions as-is
            raise
        except Exception as e:
            logger.error(
                "Track state creation failed",
                extra={
                    "event_type": "track_state_creation_failed",
                    "user_id": str(current_user.id),
                    "blood_request_id": str(track_data.blood_request_id),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal server error: {str(e)}",
            )


@router.get("/{request_id}", response_model=List[TrackStateDetailResponse])
async def get_track_states_by_request(
    request_id: UUID = Path(
        ..., description="The ID of the blood request to retrieve track states for"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage",
            "laboratory.manage",
            "blood.distribution.can_view",
            "blood.inventory.can_view",
            "blood.tracking.can_view",
        )
    ),
    request: Request = None,
):
    """
    Get all tracking states for a specific blood request.
    Requires appropriate permissions for viewing blood distributions or inventory.
    """
    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        logger.info(
            "Track states retrieval initiated",
            extra={
                "event_type": "track_states_retrieval_started",
                "user_id": str(current_user.id),
                "blood_request_id": str(request_id),
                "user_email": current_user.email,
            },
        )

        try:
            track_service = TrackStateService(db)
            # Ensure this is awaited and the service method is async
            track_states = await track_service.get_track_state(request_id)

            if not track_states:
                logger.warning(
                    "Track states not found",
                    extra={
                        "event_type": "track_states_not_found",
                        "user_id": str(current_user.id),
                        "blood_request_id": str(request_id),
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No track states found for this request",
                )

            # TODO: Add authorization check here - verify user has access to the related distribution/request
            # This would require checking if the user's facility is related to the blood request

            # Process each track state in the list
            responses = []
            for track_state in track_states:
                response = TrackStateDetailResponse(
                    **TrackStateResponse.model_validate(
                        track_state, from_attributes=True
                    ).model_dump(),
                    created_by_name=getattr(track_state, "created_by_name", None),
                )
                responses.append(response)

            logger.info(
                "Track states retrieved successfully",
                extra={
                    "event_type": "track_states_retrieved",
                    "user_id": str(current_user.id),
                    "blood_request_id": str(request_id),
                    "track_states_count": len(responses),
                },
            )

            return responses

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "Track states retrieval failed",
                extra={
                    "event_type": "track_states_retrieval_failed",
                    "user_id": str(current_user.id),
                    "blood_request_id": str(request_id),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal server error: {str(e)}",
            )


@router.get(
    "/distribution/{tracking_number}", response_model=List[TrackStateDetailResponse]
)
async def get_track_states_for_distribution(
    tracking_number: str = Path(
        ..., description="The tracking number of the distribution to get states for"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage",
            "laboratory.manage",
            "blood.distribution.can_view",
            "blood.inventory.can_view",
            "blood.tracking.can_view",
        )
    ),
    request: Request = None,
):
    """
    Get all tracking states for a specific blood distribution by tracking number.
    Requires appropriate permissions for viewing blood distributions or inventory.
    """
    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        logger.info(
            "Distribution track states retrieval initiated",
            extra={
                "event_type": "distribution_track_states_retrieval_started",
                "user_id": str(current_user.id),
                "tracking_number": tracking_number,
                "user_email": current_user.email,
            },
        )

        try:
            # Validate tracking number format (basic validation)
            if not tracking_number or len(tracking_number.strip()) == 0:
                logger.warning(
                    "Invalid tracking number provided",
                    extra={
                        "event_type": "invalid_tracking_number",
                        "user_id": str(current_user.id),
                        "tracking_number": tracking_number,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid tracking number provided",
                )

            track_service = TrackStateService(db)
            # Ensure this is awaited and the service method is async
            track_states = await track_service.get_track_states_for_distribution(
                tracking_number
            )

            if not track_states:
                logger.warning(
                    "No track states found for distribution",
                    extra={
                        "event_type": "distribution_track_states_not_found",
                        "user_id": str(current_user.id),
                        "tracking_number": tracking_number,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No track states found for this distribution",
                )

            # TODO: Add authorization check here - verify user has access to this distribution
            # This would require checking facility relationships

            # Process track states and include creator information
            responses = []
            for state in track_states:
                response = TrackStateDetailResponse(
                    **TrackStateResponse.model_validate(
                        state, from_attributes=True
                    ).model_dump(),
                    created_by_name=getattr(state, "created_by_name", None),
                )
                responses.append(response)

            logger.info(
                "Distribution track states retrieved successfully",
                extra={
                    "event_type": "distribution_track_states_retrieved",
                    "user_id": str(current_user.id),
                    "tracking_number": tracking_number,
                    "track_states_count": len(responses),
                },
            )

            return responses

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "Distribution track states retrieval failed",
                extra={
                    "event_type": "distribution_track_states_retrieval_failed",
                    "user_id": str(current_user.id),
                    "tracking_number": tracking_number,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal server error: {str(e)}",
            )


@router.patch("/{track_state_id}", response_model=TrackStateDetailResponse)
async def update_track_state(
    track_state_id: UUID = Path(..., description="The ID of the track state to update"),
    track_data: TrackStateCreate = None,  # You might want a separate update schema
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("system_administrator")),
    request: Request = None,
):
    """
    Update an existing tracking state.
    Requires appropriate permissions for managing blood distributions or inventory.
    """
    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        logger.info(
            "Track state update initiated",
            extra={
                "event_type": "track_state_update_started",
                "user_id": str(current_user.id),
                "track_state_id": str(track_state_id),
                "user_email": current_user.email,
            },
        )

        try:
            track_service = TrackStateService(db)

            # Ensure this is awaited and the service method is async
            existing_track = await track_service.get_track_state_by_id(track_state_id)
            if not existing_track:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Track state not found",
                )

            # Store old values for audit
            old_values = {
                "status": existing_track.status,
                "location": existing_track.location,
                "notes": existing_track.notes,
            }

            # Update the track state
            updated_track = await track_service.update_track_state(
                track_state_id, track_data, current_user.id
            )

            # Log audit event for track state update
            log_audit_event(
                action="update",
                resource_type="track_state",
                resource_id=str(track_state_id),
                old_values=old_values,
                new_values={
                    "status": updated_track.status,
                    "location": updated_track.location,
                    "notes": updated_track.notes,
                },
                user_id=str(current_user.id),
            )

            response = TrackStateDetailResponse(
                **TrackStateResponse.model_validate(
                    updated_track, from_attributes=True
                ).model_dump(),
                created_by_name=getattr(updated_track, "created_by_name", None),
            )

            logger.info(
                "Track state updated successfully",
                extra={
                    "event_type": "track_state_updated",
                    "track_state_id": str(track_state_id),
                    "user_id": str(current_user.id),
                    "status": updated_track.status,
                },
            )

            return response

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "Track state update failed",
                extra={
                    "event_type": "track_state_update_failed",
                    "user_id": str(current_user.id),
                    "track_state_id": str(track_state_id),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal server error: {str(e)}",
            )


# Additional endpoint for deleting track states (if needed)
@router.delete("/{track_state_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_track_state(
    track_state_id: UUID = Path(..., description="The ID of the track state to delete"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("sys.admin")),
    request: Request = None,
):
    """
    Delete a tracking state (soft delete recommended).
    Requires appropriate permissions for managing blood distributions or inventory.
    """
    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        logger.warning(
            "Track state deletion initiated",
            extra={
                "event_type": "track_state_deletion_started",
                "user_id": str(current_user.id),
                "track_state_id": str(track_state_id),
                "user_email": current_user.email,
            },
        )

        try:
            track_service = TrackStateService(db)

            # Ensure this is awaited and the service method is async
            existing_track = await track_service.get_track_state_by_id(track_state_id)
            if not existing_track:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Track state not found",
                )

            # Log security event for deletion (sensitive action)
            log_security_event(
                event_type="track_state_deletion",
                user_id=str(current_user.id),
                ip_address=(
                    getattr(request.client, "host", "unknown")
                    if request and request.client
                    else "unknown"
                ),
                details={
                    "track_state_id": str(track_state_id),
                    "status": existing_track.status,
                    "blood_request_id": str(existing_track.blood_request_id),
                },
            )

            # Store values for audit
            old_values = {
                "status": existing_track.status,
                "location": existing_track.location,
                "notes": existing_track.notes,
                "blood_request_id": str(existing_track.blood_request_id),
                "blood_distribution_id": (
                    str(existing_track.blood_distribution_id)
                    if existing_track.blood_distribution_id
                    else None
                ),
            }

            # Delete the track state
            await track_service.delete_track_state(track_state_id, current_user.id)

            # Log audit event for track state deletion
            log_audit_event(
                action="delete",
                resource_type="track_state",
                resource_id=str(track_state_id),
                old_values=old_values,
                user_id=str(current_user.id),
            )

            logger.warning(
                "Track state deleted successfully",
                extra={
                    "event_type": "track_state_deleted",
                    "track_state_id": str(track_state_id),
                    "user_id": str(current_user.id),
                },
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "Track state deletion failed",
                extra={
                    "event_type": "track_state_deletion_failed",
                    "user_id": str(current_user.id),
                    "track_state_id": str(track_state_id),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal server error: {str(e)}",
            )
            raise
        except Exception as e:
            logger.error(
                "Track state deletion failed",
                extra={
                    "event_type": "track_state_deletion_failed",
                    "user_id": str(current_user.id),
                    "track_state_id": str(track_state_id),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal server error: {str(e)}",
            )
