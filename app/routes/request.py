from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List, Optional

from app.models.user import User
from app.dependencies import get_db
from app.utils.security import get_current_user
from app.schemas.request import (
    BloodRequestCreate, 
    BloodRequestUpdate, 
    BloodRequestResponse,
    BloodRequestGroupResponse,
    BloodRequestBulkCreateResponse
)
from app.services.request import BloodRequestService
from app.models.request import RequestStatus

router = APIRouter(
    prefix="/requests",
    tags=["requests"]
)


@router.post("/", response_model=BloodRequestBulkCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_blood_request(
    request_data: BloodRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """
    Create blood requests to multiple facilities.
    
    The system will:
    1. Create individual requests for each specified facility
    2. Group them together with a common group ID
    3. Automatically cancel related requests when one is approved/fulfilled
    """
    service = BloodRequestService(db)
    return await service.create_bulk_request(request_data, requester_id=current_user.id)


@router.get("/", response_model=List[BloodRequestResponse])
async def list_my_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """List all individual requests made by the current user"""
    service = BloodRequestService(db)
    return await service.list_requests_by_user(user_id=current_user.id)


@router.get("/groups", response_model=List[BloodRequestGroupResponse])
async def list_my_request_groups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """
    List request groups made by the current user.
    
    This provides a more organized view of multi-facility requests,
    showing them as groups rather than individual requests.
    """
    service = BloodRequestService(db)
    return await service.list_request_groups_by_user(user_id=current_user.id)


@router.get("/statistics")
async def get_request_statistics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """Get request statistics for the current user"""
    service = BloodRequestService(db)
    return await service.get_request_statistics(user_id=current_user.id)


@router.get("/groups/{request_group_id}", response_model=BloodRequestGroupResponse)
async def get_request_group(
    request_group_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """Get detailed information about a request group"""
    service = BloodRequestService(db)
    group = await service.get_request_group(request_group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Request group not found")
    
    # Verify ownership
    if group.master_request.requester_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this request group")
    
    return group


@router.get("/{request_id}", response_model=BloodRequestResponse)
async def get_blood_request(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """Get a specific blood request by ID"""
    service = BloodRequestService(db)
    request = await service.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Verify ownership
    if request.requester_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this request")
    
    return request


@router.patch("/{request_id}", response_model=BloodRequestResponse)
async def update_blood_request(
    request_id: UUID,
    update_data: BloodRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """
    Update a blood request.
    
    Note: If the status is changed to approved or fulfilled,
    all related requests in the same group will be automatically cancelled.
    """
    service = BloodRequestService(db)
    
    # Verify ownership first
    request = await service.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    if request.requester_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this request")
    
    return await service.update_request(request_id, update_data)


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blood_request(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """Delete a blood request (only if pending or cancelled)"""
    service = BloodRequestService(db)
    
    # Verify ownership first
    request = await service.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    if request.requester_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this request")
    
    await service.delete_request(request_id)
    return {"detail": "Blood request deleted successfully"}


@router.get("/status/{status}", response_model=List[BloodRequestResponse])
async def list_requests_by_status(
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """List requests by status for the current user"""
    service = BloodRequestService(db)
    try:
        request_status = RequestStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request status")
    
    # Get all requests by status, then filter by user
    all_requests = await service.list_requests_by_status(request_status)
    user_requests = [req for req in all_requests if req.requester_id == current_user.id]
    
    return user_requests


# Routes for facility managers/staff
@router.get("/facility/{facility_id}", response_model=List[BloodRequestResponse])
async def list_facility_requests(
    facility_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """
    List all requests for a specific facility.
    
    This endpoint is typically used by facility managers/staff
    to view requests made to their facility.
    """
    service = BloodRequestService(db)
    
    # Note: You might want to add authorization logic here
    # to ensure only facility staff can view requests for their facility
    
    return await service.list_requests_by_facility(facility_id)


@router.patch("/facility/{request_id}/respond", response_model=BloodRequestResponse)
async def respond_to_request(
    request_id: UUID,
    response_data: BloodRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    """
    Allow facility staff to respond to a blood request.
    
    This endpoint is designed for facility managers/staff to approve,
    reject, or fulfill requests made to their facility.
    """
    service = BloodRequestService(db)
    
    # Get the request first
    request = await service.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Note: Add authorization logic here to ensure only facility staff
    # can respond to requests made to their facility
    
    # Set the fulfilled_by field if status is being set to fulfilled
    if response_data.status == RequestStatus.fulfilled:
        response_data.fulfilled_by_id = current_user.id
    
    return await service.update_request(request_id, response_data)