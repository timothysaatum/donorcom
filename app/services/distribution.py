from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from fastapi import HTTPException
from uuid import UUID
from app.models import BloodDistribution, BloodInventory, User
from app.schemas.distribution import BloodDistributionCreate, BloodDistributionUpdate
from typing import Optional, List


class BloodDistributionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_distribution(self, distribution_data: BloodDistributionCreate, created_by: User) -> BloodDistribution:
        """
        Create a new blood distribution. Automatically assigns user's facility as dispatched_to.
        """
        if not created_by.facility:
            raise HTTPException(status_code=400, detail="User is not assigned to any facility.")

        # Validate blood product exists
        result = await self.db.execute(select(BloodInventory).where(BloodInventory.id == distribution_data.blood_product_id))
        blood_product = result.scalar_one_or_none()
        if not blood_product:
            raise HTTPException(status_code=404, detail="Blood product not found.")

        distribution = BloodDistribution(
            **distribution_data.model_dump(exclude={"dispatched_to_id"}),
            dispatched_to_id=created_by.facility.id,
            created_by_id=created_by.id
        )

        self.db.add(distribution)
        await self.db.commit()
        await self.db.refresh(distribution)

        return distribution

    async def get_distribution(self, distribution_id: UUID) -> Optional[BloodDistribution]:
        result = await self.db.execute(
            select(BloodDistribution)
            .options(joinedload(BloodDistribution.blood_product), joinedload(BloodDistribution.dispatched_to))
            .where(BloodDistribution.id == distribution_id)
        )
        return result.scalar_one_or_none()

    async def update_distribution(self, distribution_id: UUID, update_data: BloodDistributionUpdate) -> BloodDistribution:
        distribution = await self.get_distribution(distribution_id)
        if not distribution:
            raise HTTPException(status_code=404, detail="Distribution not found")

        update_fields = update_data.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            setattr(distribution, field, value)

        await self.db.commit()
        await self.db.refresh(distribution)
        return distribution

    async def delete_distribution(self, distribution_id: UUID) -> bool:
        distribution = await self.get_distribution(distribution_id)
        if not distribution:
            raise HTTPException(status_code=404, detail="Distribution not found")

        await self.db.delete(distribution)
        await self.db.commit()
        return True

    async def list_distributions(self) -> List[BloodDistribution]:
        result = await self.db.execute(
            select(BloodDistribution)
            .options(joinedload(BloodDistribution.blood_product), joinedload(BloodDistribution.dispatched_to))
        )
        return result.scalars().all()

    async def list_my_facility_distributions(self, facility_id: UUID) -> List[BloodDistribution]:
        result = await self.db.execute(
            select(BloodDistribution)
            .where(BloodDistribution.dispatched_to_id == facility_id)
            .options(joinedload(BloodDistribution.blood_product))
        )
        return result.scalars().all()
