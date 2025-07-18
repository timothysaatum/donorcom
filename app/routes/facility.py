from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.facility_schema import (
    FacilityBase, 
    FacilityResponse, 
    FacilityUpdate,
    FacilityWithBloodBankCreate,
    FacilityWithBloodBank
)
from app.services.facility_service import FacilityService
from app.models.user import User
from app.utils.security import get_current_user
from app.dependencies import get_db
from uuid import UUID
from typing import List, Union
from app.models.health_facility import Facility
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload


router = APIRouter(
    prefix="/facilities",
    tags=["facilities"]
)


@router.post("/create", response_model=FacilityResponse)
async def create_facility(
    facility_data: FacilityBase, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "facility_administrator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You do not have permission"
        )

    facility_service = FacilityService(db)
    new_facility = await facility_service.create_facility(
        facility_data=facility_data,
        facility_manager_id=current_user.id
    )

    return FacilityResponse.model_validate(new_facility, from_attributes=True)


@router.post("/create-with-blood-bank", response_model=Union[FacilityResponse, FacilityWithBloodBank])
async def create_facility_with_blood_bank(
    data: FacilityWithBloodBankCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a facility and optionally its associated blood bank in a single request
    """
    if current_user.role != "facility_administrator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission"
        )

    facility_service = FacilityService(db)
    result = await facility_service.create_facility_with_blood_bank(
        data=data,
        facility_manager_id=current_user.id
    )

    return result


@router.get("/get-facility-by-id/{facility_id}", response_model=FacilityResponse)
async def get_facility_by_id(facility_id: UUID, db: AsyncSession = Depends(get_db)):
    # Eagerly load the facility_manager relationship
    result = await db.execute(
        select(Facility)
        .options(selectinload(Facility.facility_manager))
        .where(Facility.id == facility_id)
    )

    facility = result.scalar_one_or_none()

    if not facility:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facility not found")

    return FacilityResponse.model_validate(facility, from_attributes=True)


@router.get("/all", response_model=List[FacilityResponse])
async def get_all_facilities(db: AsyncSession = Depends(get_db)):
    facility_service = FacilityService(db)
    return await facility_service.get_all_facilities()


@router.patch("/update-facility/{facility_id}", response_model=FacilityResponse)
async def update_facility(
    facility_id: UUID, 
    facility_data: FacilityUpdate, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    facility_service = FacilityService(db)
    existing_facility = await facility_service.get_facility(facility_id)

    if not existing_facility:
        raise HTTPException(status_code=404, detail="Facility not found")

    if existing_facility.facility_manager_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")

    updated_facility = await facility_service.update_facility(facility_id, facility_data)

    return updated_facility


@router.delete("/delete-facility/{facility_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_facility(
    facility_id: UUID, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    # Ensure the user is the facility manager for this facility
    facility_service = FacilityService(db)
    facility = await facility_service.get_facility(facility_id)

    if not facility:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facility not found")

    if facility.facility_manager_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You do not have permission to delete this facility"
        )

    await facility_service.delete_facility(facility_id)
    
    return {"detail": "Facility deleted successfully"}