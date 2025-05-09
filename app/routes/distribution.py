from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.schemas.distribution import BloodDistributionCreate, BloodDistributionResponse, BloodDistributionUpdate
from app.services.distribution import BloodDistributionService
from app.dependencies import get_db
from app.utils.security import get_current_user
from app.models import User

router = APIRouter(prefix="/distributions", tags=["Distributions"])


@router.post("/", response_model=BloodDistributionResponse)
async def create_distribution(
    distribution_data: BloodDistributionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = BloodDistributionService(db)
    return await service.create_distribution(distribution_data, current_user)


@router.get("/", response_model=list[BloodDistributionResponse])
async def list_my_distributions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.facility:
        raise HTTPException(status_code=400, detail="User has no facility assigned.")
    service = BloodDistributionService(db)
    return await service.list_my_facility_distributions(current_user.facility.id)


@router.get("/{distribution_id}", response_model=BloodDistributionResponse)
async def get_distribution(
    distribution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = BloodDistributionService(db)
    distribution = await service.get_distribution(distribution_id)
    if not distribution:
        raise HTTPException(status_code=404, detail="Distribution not found")
    return distribution


@router.patch("/{distribution_id}", response_model=BloodDistributionResponse)
async def update_distribution(
    distribution_id: UUID,
    update_data: BloodDistributionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = BloodDistributionService(db)
    return await service.update_distribution(distribution_id, update_data)


@router.delete("/{distribution_id}", status_code=204)
async def delete_distribution(
    distribution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = BloodDistributionService(db)
    await service.delete_distribution(distribution_id)
    return None
