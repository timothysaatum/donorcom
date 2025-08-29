from app.models.health_facility import Facility
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_
from app.schemas.distribution import (
    BloodDistributionCreate, 
    BloodDistributionResponse, 
    BloodDistributionUpdate, 
    BloodDistributionDetailResponse,
    DistributionStatus
)
from app.services.distribution import BloodDistributionService
from app.models.user import User
from app.models.blood_bank import BloodBank
from app.models.distribution import BloodDistributionStatus
from app.utils.security import get_current_user
from app.utils.permission_checker import require_permission
from app.dependencies import get_db
from uuid import UUID
from typing import List, Optional
from datetime import datetime

router = APIRouter(
    prefix="/blood-distribution",
    tags=["blood distribution"]
)


# Helper function to get blood bank ID for the current user
async def get_user_blood_bank_id(db: AsyncSession, user_id: UUID) -> UUID:
    """Get the blood bank ID associated with the user"""
    
    result = await db.execute(
    select(BloodBank).where(
        or_(
            # Case 1: User is the blood bank manager
            BloodBank.manager_id == user_id,

            # Case 2: User is staff working in the facility
            BloodBank.facility_id == (
                select(User.work_facility_id)
                .where(User.id == user_id)
                .scalar_subquery()
            ),

            # Case 3: User is the facility manager
            BloodBank.facility_id == (
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
        detail="You are not associated with any blood bank"
    )


@router.post("/", response_model=BloodDistributionDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_distribution(
    distribution_data: BloodDistributionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.issue.can_create"
    ))
):
    """
    Create a new blood distribution.
    The blood bank and user who created it are automatically assigned.
    """
    # Get the blood bank associated with the user
    blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    # Get the facility ID associated with this blood bank to prevent self-distribution
    result = await db.execute(
        select(BloodBank).where(BloodBank.id == blood_bank_id)
    )
    blood_bank = result.scalar_one()
    
    # Check if the destination facility is the same as the source blood bank's facility
    if blood_bank.facility_id == distribution_data.dispatched_to_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot distribute blood to your own facility"
        )
    
    distribution_service = BloodDistributionService(db)
    new_distribution = await distribution_service.create_distribution(
        distribution_data=distribution_data,
        blood_bank_id=blood_bank_id,
        created_by_id=current_user.id
    )
    
    # Commit the transaction since we removed the transaction context in the service
    await db.commit()
    
    # Format the response with additional information
    response = BloodDistributionDetailResponse(
        **BloodDistributionResponse.model_validate(new_distribution, from_attributes=True).model_dump(),
        dispatched_from_name=new_distribution.dispatched_from.blood_bank_name if new_distribution.dispatched_from else None,
        dispatched_to_name=new_distribution.dispatched_to.facility_name if new_distribution.dispatched_to else None,
        created_by_name=new_distribution.created_by.last_name if new_distribution.created_by else None
    )
    
    return response


@router.get("/{distribution_id}", response_model=BloodDistributionDetailResponse)
async def get_distribution(
    distribution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.issue.can_view"
    ))
):
    """Get details of a specific blood distribution"""
    distribution_service = BloodDistributionService(db)
    distribution = await distribution_service.get_distribution(distribution_id)
    
    if not distribution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood distribution not found"
        )
    
    # Authorization check: user must be associated with either the sending blood bank or receiving facility
    blood_bank_id = await get_user_blood_bank_id(db, current_user.id)

    # Restrict access to dispatching or receiving blood bank
    if (
        distribution.dispatched_from_id != blood_bank_id or 
        distribution.dispatched_to_id != blood_bank_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view this distribution"
        )
    
    # Format response with additional information
    response = BloodDistributionDetailResponse(
        **BloodDistributionResponse.model_validate(distribution, from_attributes=True).model_dump(),
        dispatched_from_name=distribution.dispatched_from.blood_bank_name if distribution.dispatched_from else None,
        dispatched_to_name=distribution.dispatched_to.facility_name if distribution.dispatched_to else None,
        created_by_name=distribution.created_by.last_name if distribution.created_by else None
    )
    
    return response


@router.get("/", response_model=List[BloodDistributionDetailResponse])
async def list_distributions(
    status: Optional[DistributionStatus] = None,
    facility_id: Optional[UUID] = None,
    recent_days: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.issue.can_view"
    ))
):
    """
    List blood distributions with optional filtering.
    Can filter by status, facility, or recent distributions.
    Only returns distributions associated with the user's blood bank.
    """
    # Get the blood bank associated with the user
    blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    if not blood_bank_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with any blood bank"
        )
    distribution_service = BloodDistributionService(db)
    
    # Get all distributions for this blood bank first
    blood_bank_distributions = await distribution_service.get_distributions_by_blood_bank(blood_bank_id)
    
    # Apply additional filters if specified
    if status:
        enum_status = BloodDistributionStatus[status]
        filtered_distributions = [d for d in blood_bank_distributions if d.status == enum_status]
    elif facility_id:
        filtered_distributions = [d for d in blood_bank_distributions if d.dispatched_to_id == facility_id]
    elif recent_days:
        cutoff_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_date = cutoff_date.replace(day=cutoff_date.day - recent_days)
        filtered_distributions = [d for d in blood_bank_distributions if d.created_at >= cutoff_date]
    else:
        filtered_distributions = blood_bank_distributions
    
    # Format each distribution for response
    return [
        BloodDistributionDetailResponse(
            **BloodDistributionResponse.model_validate(dist, from_attributes=True).model_dump(),
            dispatched_from_name=dist.dispatched_from.blood_bank_name if dist.dispatched_from else None,
            dispatched_to_name=dist.dispatched_to.facility_name if dist.dispatched_to else None,
            created_by_name=dist.created_by.last_name if dist.created_by else None
        )
        for dist in filtered_distributions
    ]


@router.patch("/{distribution_id}", response_model=BloodDistributionDetailResponse)
async def update_distribution(
    distribution_id: UUID,
    distribution_data: BloodDistributionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.issue.can_update"
    ))
):
    """
    Update a blood distribution.
    User must be associated with the blood bank that owns this distribution.
    """
    distribution_service = BloodDistributionService(db)
    distribution = await distribution_service.get_distribution(distribution_id)
    
    if not distribution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood distribution not found"
        )
    
    # Check if user is associated with this blood bank
    user_blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    if distribution.dispatched_from_id != user_blood_bank_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this distribution"
        )
    
    # Convert string status to enum if present
    if distribution_data.status:
        # The enum value is already handled by Pydantic conversion
        pass
    
    updated_distribution = await distribution_service.update_distribution(
        distribution_id, 
        distribution_data
    )
    
    # Format response
    response = BloodDistributionDetailResponse(
        **BloodDistributionResponse.model_validate(updated_distribution, from_attributes=True).model_dump(),
        dispatched_from_name=updated_distribution.dispatched_from.blood_bank_name if updated_distribution.dispatched_from else None,
        dispatched_to_name=updated_distribution.dispatched_to.facility_name if updated_distribution.dispatched_to else None,
        created_by_name=updated_distribution.created_by.last_name if updated_distribution.created_by else None
    )
    
    return response


@router.delete("/{distribution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_distribution(
    distribution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.issue.can_delete"
    ))
):
    """
    Delete a blood distribution.
    User must be associated with the blood bank that owns this distribution.
    Only pending distributions can be deleted.
    """
    distribution_service = BloodDistributionService(db)
    distribution = await distribution_service.get_distribution(distribution_id)
    
    if not distribution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blood distribution not found"
        )
    
    # Check if user is associated with this blood bank
    user_blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    if distribution.dispatched_from_id != user_blood_bank_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this distribution"
        )
    
    await distribution_service.delete_distribution(distribution_id)
    return {"detail": "Blood distribution deleted successfully"}


@router.get("/facility/{facility_id}", response_model=List[BloodDistributionDetailResponse])
async def get_distributions_by_facility(
    facility_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.issue.can_view"
    ))
):
    """
    Get all blood distributions for a specific facility from the user's blood bank.
    """
    # Get the blood bank associated with the user
    blood_bank_id = await get_user_blood_bank_id(db, current_user.id)
    
    distribution_service = BloodDistributionService(db)
    all_distributions = await distribution_service.get_distributions_by_facility(facility_id)
    # Filter to only include distributions from this user's blood bank
    user_distributions = [
        dist for dist in all_distributions
        if dist.dispatched_from_id == blood_bank_id
    ]
    return user_distributions