from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload, joinedload
from fastapi import HTTPException
from uuid import UUID
from app.models.inventory import BloodInventory
from app.schemas.inventory import BloodInventoryCreate, BloodInventoryUpdate
from typing import Optional, List



class BloodInventoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_blood_unit(self, 
                               blood_data: BloodInventoryCreate, 
                               blood_bank_id: UUID, 
                               added_by_id: UUID) -> BloodInventory:
        """
        Create a new blood unit inventory entry
        """
        new_blood_unit = BloodInventory(
            **blood_data.model_dump(),
            blood_bank_id=blood_bank_id,
            added_by_id=added_by_id
        )

        self.db.add(new_blood_unit)
        await self.db.commit()
        await self.db.refresh(new_blood_unit)
        
        # Load relationships
        await self.db.refresh(new_blood_unit, attribute_names=["blood_bank", "added_by"])
        
        return new_blood_unit

    async def get_blood_unit(self, blood_unit_id: UUID) -> Optional[BloodInventory]:
        """
        Get a blood unit by ID
        """
        result = await self.db.execute(
            select(BloodInventory)
            .options(joinedload(BloodInventory.blood_bank), joinedload(BloodInventory.added_by))
            .where(BloodInventory.id == blood_unit_id)
        )
        return result.scalar_one_or_none()

    async def update_blood_unit(self, blood_unit_id: UUID, blood_data: BloodInventoryUpdate) -> BloodInventory:
        """
        Update a blood unit
        """
        blood_unit = await self.get_blood_unit(blood_unit_id)
        if not blood_unit:
            raise HTTPException(status_code=404, detail="Blood unit not found")

        update_data = blood_data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(blood_unit, field, value)

        # Update the updated_at timestamp
        await self.db.commit()
        await self.db.refresh(blood_unit)

        return blood_unit

    async def delete_blood_unit(self, blood_unit_id: UUID) -> bool:
        """
        Delete a blood unit
        """
        blood_unit = await self.get_blood_unit(blood_unit_id)
        if not blood_unit:
            raise HTTPException(status_code=404, detail="Blood unit not found")

        await self.db.delete(blood_unit)
        await self.db.commit()
        return True

    async def get_all_blood_units(self) -> List[BloodInventory]:
        """
        Get all blood units with their relationships
        """
        result = await self.db.execute(
            select(BloodInventory)
            .options(joinedload(BloodInventory.blood_bank), joinedload(BloodInventory.added_by))
        )
        return result.scalars().all()

    async def get_blood_units_by_bank(self, blood_bank_id: UUID) -> List[BloodInventory]:
        """
        Get all blood units for a specific blood bank
        """
        result = await self.db.execute(
            select(BloodInventory)
            .options(joinedload(BloodInventory.blood_bank), joinedload(BloodInventory.added_by))
            .where(BloodInventory.blood_bank_id == blood_bank_id)
        )
        return result.scalars().all()
    
    async def get_expiring_blood_units(self, days: int = 7) -> List[BloodInventory]:
        """
        Get blood units expiring in the next X days
        """
        from datetime import datetime, timedelta
        expiry_threshold = datetime.now().date() + timedelta(days=days)
        
        result = await self.db.execute(
            select(BloodInventory)
            .options(joinedload(BloodInventory.blood_bank), joinedload(BloodInventory.added_by))
            .where(BloodInventory.expiry_date <= expiry_threshold)
            .order_by(BloodInventory.expiry_date)
        )
        return result.scalars().all()

    async def get_blood_units_by_type(self, blood_type: str) -> List[BloodInventory]:
        """
        Get all blood units of a specific blood type
        """
        result = await self.db.execute(
            select(BloodInventory)
            .options(joinedload(BloodInventory.blood_bank), joinedload(BloodInventory.added_by))
            .where(BloodInventory.blood_type == blood_type)
        )
        return result.scalars().all()