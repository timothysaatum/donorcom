from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.blood_bank import BloodBankCreate, BloodBankResponse, BloodBankUpdate, BloodBankBase
from app.services.blood_bank import BloodBankService
from app.models.user import User
from app.utils.security import get_current_user
from app.dependencies import get_db
from uuid import UUID
from typing import List
from app.models.blood_bank import BloodBank
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload



router = APIRouter(
    prefix="/blood-banks",
    tags=["blood banks"]
)


@router.post("/create", response_model=BloodBankResponse)
async def create_blood_bank(blood_bank_data: BloodBankBase, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):

    """
    Create a new blood bank with the current user as manager.
    Only facility administrators can create blood banks.
    """

    # Check if the user is a facility administrator
    if current_user.role != "facility_administrator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Only facility administrators can create blood banks"
        )

    # Check if the user already manages any facility
    result = await db.execute(
        select(BloodBank).where(BloodBank.manager_id == current_user.id)
    )

    if result.scalar_one_or_none():
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

    return BloodBankResponse.model_validate(new_blood_bank, from_attributes=True)



@router.get("/get-blood-bank/{blood_bank_id}", response_model=BloodBankResponse)
async def get_blood_bank_by_id(blood_bank_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get blood bank details by ID"""
    # Eagerly load the relationships
    result = await db.execute(
        select(BloodBank)
        .options(selectinload(BloodBank.facility), selectinload(BloodBank.manager_user))
        .where(BloodBank.id == blood_bank_id)
    )

    blood_bank = result.scalar_one_or_none()

    if not blood_bank:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Blood bank not found"
        )

    return BloodBankResponse.model_validate(blood_bank, from_attributes=True)



@router.get("/all", response_model=List[BloodBankResponse])
async def get_all_blood_banks(db: AsyncSession = Depends(get_db)):
    """Get all blood banks"""
    blood_bank_service = BloodBankService(db)
    return await blood_bank_service.get_all_blood_banks()



@router.patch("/update/{blood_bank_id}", response_model=BloodBankResponse)
async def update_blood_bank(

    blood_bank_id: UUID, 
    blood_bank_data: BloodBankUpdate, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_current_user)

    ):
    """
    Update blood bank details. 
    Only the manager of the blood bank can update it.
    """
    blood_bank_service = BloodBankService(db)
    existing_blood_bank = await blood_bank_service.get_blood_bank(blood_bank_id)

    if not existing_blood_bank:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Blood bank not found"
        )

    # Check if the current user is the manager of this blood bank
    if existing_blood_bank.manager_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You do not have permission to update this blood bank"
        )

    updated_blood_bank = await blood_bank_service.update_blood_bank(blood_bank_id, blood_bank_data)

    return BloodBankResponse.model_validate(updated_blood_bank, from_attributes=True)


@router.delete("/delete/{blood_bank_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blood_bank(

    blood_bank_id: UUID, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_current_user)

    ):

    """
    Delete a blood bank.
    Only the manager of the blood bank can delete it.
    """

    # Get the blood bank
    blood_bank_service = BloodBankService(db)
    blood_bank = await blood_bank_service.get_blood_bank(blood_bank_id)

    if not blood_bank:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Blood bank not found"
        )

    # Check if the current user is the manager
    if blood_bank.manager_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You do not have permission to delete this blood bank"
        )

    await blood_bank_service.delete_blood_bank(blood_bank_id)

    return {"detail": "Blood bank deleted successfully"}