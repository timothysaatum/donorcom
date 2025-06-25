from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List

from app.models.user import User
from app.dependencies import get_db
from app.utils.security import get_current_user
from app.schemas.request import BloodRequestCreate, BloodRequestUpdate, BloodRequestResponse
from app.services.request import BloodRequestService
from app.models.request import RequestStatus

router = APIRouter(
    prefix="/requests",
    tags=["requests"]
)


@router.post("/", response_model=BloodRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_blood_request(
    request_data: BloodRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = BloodRequestService(db)
    return await service.create_request(request_data, requester_id=current_user.id)


@router.get("/", response_model=List[BloodRequestResponse])
async def list_my_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = BloodRequestService(db)
    return await service.list_requests_by_user(user_id=current_user.id)


@router.get("/{request_id}", response_model=BloodRequestResponse)
async def get_blood_request(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = BloodRequestService(db)
    request = await service.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    return request


@router.patch("/{request_id}", response_model=BloodRequestResponse)
async def update_blood_request(
    request_id: UUID,
    update_data: BloodRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = BloodRequestService(db)
    return await service.update_request(request_id, update_data)


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blood_request(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = BloodRequestService(db)
    await service.delete_request(request_id)
    return {"detail": "Blood request deleted successfully"}


@router.get("/status/{status}", response_model=List[BloodRequestResponse])
async def list_requests_by_status(
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = BloodRequestService(db)
    try:
        request_status = RequestStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request status")
    
    return await service.list_requests_by_status(request_status)