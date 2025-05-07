from fastapi import APIRouter, Depends, HTTPException, status, Path
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.inventory import BloodInventoryCreate, BloodInventoryResponse, BloodInventoryUpdate, BloodInventoryDetailResponse
from app.services.inventory import BloodInventoryService
from app.models.user import User
from app.utils.security import get_current_user
from app.dependencies import get_db
from uuid import UUID
from typing import List, Optional
from sqlalchemy.future import select
from app.models.blood_bank import BloodBank


router = APIRouter(
    prefix="/blood-inventory",
    tags=["blood inventory"]
)


# Helper function to get blood bank ID for the current user
async def get_user_blood_bank_id(db: AsyncSession, user_id: UUID) -> UUID:
    """Get the blood bank ID associated with the user"""
    # Check if user is directly a blood bank manager
    result = await db.execute(
        select(BloodBank).where(BloodBank.manager_id == user_id)
    )
    blood_bank = result.scalar_one_or_none()
    
    if blood_bank:
        return blood_bank.id
    
    # TODO: If you have staff associations in your model, you could add additional logic here
    # to check if the user is a staff member at a blood bank
    
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You are not associated with any blood bank"
    )


@router.post("/", response_model=BloodInventoryResponse, status_code=status.HTTP_201_CREATED)
async def create_blood_unit(
    blood_data: BloodInventoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Add a new blood unit to inventory.
    The blood bank and user who added it are automatically assigned.
    """
    # Get the blood bank associated with the user
    blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    blood_service = BloodInventoryService(db)
    new_blood_unit = await blood_service.create_blood_unit(
        blood_data=blood_data,
        blood_bank_id=blood_bank_id,
        added_by_id=current_user.id
    )
    
    return BloodInventoryResponse.model_validate(new_blood_unit, from_attributes=True)


@router.get("/{blood_unit_id}", response_model=BloodInventoryDetailResponse)
async def get_blood_unit(
    blood_unit_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific blood unit"""
    blood_service = BloodInventoryService(db)
    blood_unit = await blood_service.get_blood_unit(blood_unit_id)
    
    if not blood_unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood unit not found"
        )
    
    # Create response with additional fields
    response = BloodInventoryDetailResponse(
        **BloodInventoryResponse.model_validate(blood_unit, from_attributes=True).model_dump(),
        blood_bank_name=blood_unit.blood_bank.blood_bank_name if blood_unit.blood_bank else None,
        added_by_name=blood_unit.added_by.name if blood_unit.added_by else None
    )
    
    return response


@router.get("/", response_model=List[BloodInventoryDetailResponse])
async def list_blood_units(
    blood_bank_id: Optional[UUID] = None,
    blood_type: Optional[str] = None,
    expiring_in_days: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    List blood units with optional filtering.
    Can filter by blood bank, blood type, or units expiring soon.
    """
    blood_service = BloodInventoryService(db)
    
    if blood_bank_id:
        blood_units = await blood_service.get_blood_units_by_bank(blood_bank_id)
    elif blood_type:
        blood_units = await blood_service.get_blood_units_by_type(blood_type)
    elif expiring_in_days:
        blood_units = await blood_service.get_expiring_blood_units(expiring_in_days)
    else:
        blood_units = await blood_service.get_all_blood_units()
    
    return [
        BloodInventoryDetailResponse(
            **BloodInventoryResponse.model_validate(unit, from_attributes=True).model_dump(),
            blood_bank_name=unit.blood_bank.blood_bank_name if unit.blood_bank else None,
            added_by_name=unit.added_by.name if unit.added_by else None
        )
        for unit in blood_units
    ]


@router.patch("/{blood_unit_id}", response_model=BloodInventoryResponse)
async def update_blood_unit(
    blood_unit_id: UUID,
    blood_data: BloodInventoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update a blood unit.
    User must be associated with the blood bank that owns this unit.
    """
    blood_service = BloodInventoryService(db)
    blood_unit = await blood_service.get_blood_unit(blood_unit_id)
    
    if not blood_unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood unit not found"
        )
    
    # Check if user is associated with this blood bank
    user_blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    if blood_unit.blood_bank_id != user_blood_bank_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this blood unit"
        )
    
    updated_unit = await blood_service.update_blood_unit(blood_unit_id, blood_data)
    return BloodInventoryResponse.model_validate(updated_unit, from_attributes=True)


@router.delete("/{blood_unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blood_unit(
    blood_unit_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a blood unit.
    User must be associated with the blood bank that owns this unit.
    """
    blood_service = BloodInventoryService(db)
    blood_unit = await blood_service.get_blood_unit(blood_unit_id)
    
    if not blood_unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood unit not found"
        )
    
    # Check if user is associated with this blood bank
    user_blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    if blood_unit.blood_bank_id != user_blood_bank_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this blood unit"
        )
    
    await blood_service.delete_blood_unit(blood_unit_id)
    return {"detail": "Blood unit deleted successfully"}


@router.get("/bank/{blood_bank_id}", response_model=List[BloodInventoryDetailResponse])
async def get_blood_units_by_bank(
    blood_bank_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get all blood units for a specific blood bank"""
    blood_service = BloodInventoryService(db)
    blood_units = await blood_service.get_blood_units_by_bank(blood_bank_id)
    
    return [
        BloodInventoryDetailResponse(
            **BloodInventoryResponse.model_validate(unit, from_attributes=True).model_dump(),
            blood_bank_name=unit.blood_bank.blood_bank_name if unit.blood_bank else None,
            added_by_name=unit.added_by.name if unit.added_by else None
        )
        for unit in blood_units
    ]


@router.get("/expiring/{days}", response_model=List[BloodInventoryDetailResponse])
async def get_expiring_blood_units(
    days: int = Path(..., ge=1, le=90, description="Number of days to check for expiration"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get blood units expiring in the specified number of days.
    Only shows units from the blood bank associated with the current user.
    """
    # Get the blood bank associated with the user
    blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    blood_service = BloodInventoryService(db)
    all_expiring = await blood_service.get_expiring_blood_units(days)
    
    # Filter to only show units from the user's blood bank
    expiring_units = [unit for unit in all_expiring if unit.blood_bank_id == blood_bank_id]
    
    return [
        BloodInventoryDetailResponse(
            **BloodInventoryResponse.model_validate(unit, from_attributes=True).model_dump(),
            blood_bank_name=unit.blood_bank.blood_bank_name if unit.blood_bank else None,
            added_by_name=unit.added_by.name if unit.added_by else None
        )
        for unit in expiring_units
    ]