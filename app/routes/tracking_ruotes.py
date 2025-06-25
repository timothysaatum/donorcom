# routes/track_state.py
from fastapi import APIRouter, Depends, HTTPException, status, Path
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.tracking_schema import (
    TrackStateCreate,
    TrackStateResponse,
    TrackStateDetailResponse,
    # TrackStateStatus
)
from app.services.tracking_service import TrackStateService
from app.models.user import User
from app.dependencies import get_db
from app.utils.security import get_current_user
from uuid import UUID
from typing import List

router = APIRouter(
    prefix="/track-states",
    tags=["track states"]
)

@router.post("/", response_model=TrackStateDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_track_state(
    track_data: TrackStateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new tracking state for a blood distribution.
    """
    track_service = TrackStateService(db)
    
    # Verify the user has access to this distribution (you might want to add more checks)
    # This would require a distribution service check
    
    new_track = await track_service.create_track_state(track_data, current_user.id)
    
    # Format the response with additional details
    response = TrackStateDetailResponse(
        **TrackStateResponse.model_validate(new_track, from_attributes=True).model_dump(),
        created_by_name=current_user.last_name
    )
    
    return response

@router.get("/{track_state_id}", response_model=TrackStateDetailResponse)
async def get_track_state(
    track_state_id: UUID = Path(..., description="The ID of the track state to retrieve"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get details of a specific tracking state.
    """
    track_service = TrackStateService(db)
    track_state = await track_service.get_track_state(track_state_id)
    
    if not track_state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track state not found"
        )
    
    # Add authorization check here - verify user has access to the related distribution
    
    # Format response
    response = TrackStateDetailResponse(
        **TrackStateResponse.model_validate(track_state, from_attributes=True).model_dump(),
        created_by_name=track_state.created_by.last_name if track_state.created_by else None
    )
    
    return response

@router.get("/distribution/{tracking_number}", response_model=List[TrackStateDetailResponse])
async def get_track_states_for_distribution(
    tracking_number: str = Path(..., description="The ID of the distribution to get states for"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all tracking states for a specific blood distribution.
    """
    track_service = TrackStateService(db)
    track_states = await track_service.get_track_states_for_distribution(tracking_number)
    
    # Add authorization check here - verify user has access to this distribution
    
    return [
        TrackStateDetailResponse(
            **TrackStateResponse.model_validate(state, from_attributes=True).model_dump(),
            created_by_name=state.created_by.last_name if state.created_by else None
        )
        for state in track_states
    ]

@router.get("/distribution/{distribution_id}/latest", response_model=TrackStateDetailResponse)
async def get_latest_track_state(
    distribution_id: UUID = Path(..., description="The ID of the distribution to get latest state for"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get the most recent tracking state for a distribution.
    """
    track_service = TrackStateService(db)
    track_state = await track_service.get_latest_state_for_distribution(distribution_id)
    
    if not track_state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No track states found for this distribution"
        )
    
    # Add authorization check here
    
    response = TrackStateDetailResponse(
        **TrackStateResponse.model_validate(track_state, from_attributes=True).model_dump(),
        created_by_name=track_state.created_by.last_name if track_state.created_by else None
    )
    
    return response

@router.delete("/{track_state_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_track_state(
    track_state_id: UUID = Path(..., description="The ID of the track state to delete"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a tracking state.
    """
    track_service = TrackStateService(db)
    success = await track_service.delete_track_state(track_state_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track state not found"
        )
    
    return None