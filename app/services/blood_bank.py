from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException
from uuid import UUID
from app.models import BloodBank
from app.schemas.blood_bank import (
    BloodBankCreate,
    BloodBankUpdate,
    BloodBankResponse
)
from typing import Optional, List

class BloodBankService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_blood_bank(self, blood_bank_data: BloodBankCreate) -> BloodBankResponse:
        # Check duplicate email
        result = await self.db.execute(
            select(BloodBank).where(BloodBank.email == blood_bank_data.email)
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Blood bank with this email already exists")

        new_blood_bank = BloodBank(**blood_bank_data.model_dump())

        self.db.add(new_blood_bank)
        await self.db.commit()
        await self.db.refresh(new_blood_bank)

        # Eager-load relationships if needed
        await self.db.refresh(new_blood_bank, attribute_names=["facility", "manager_user"])

        return new_blood_bank

    async def get_blood_bank(self, blood_bank_id: UUID) -> Optional[BloodBank]:
        result = await self.db.execute(
            select(BloodBank).where(BloodBank.id == blood_bank_id)
        )
        return result.scalar_one_or_none()

    async def update_blood_bank(self, blood_bank_id: UUID, blood_bank_data: BloodBankUpdate) -> BloodBankResponse:
        blood_bank = await self.get_blood_bank(blood_bank_id)
        if not blood_bank:
            raise HTTPException(status_code=404, detail="Blood bank not found")

        update_data = blood_bank_data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(blood_bank, field, value)

        await self.db.commit()
        await self.db.refresh(blood_bank)

        return blood_bank

    async def delete_blood_bank(self, blood_bank_id: UUID) -> bool:
        blood_bank = await self.get_blood_bank(blood_bank_id)
        if not blood_bank:
            raise HTTPException(status_code=404, detail="Blood bank not found")

        await self.db.delete(blood_bank)
        await self.db.commit()
        return True

    async def get_all_blood_banks(self) -> List[BloodBankResponse]:
        result = await self.db.execute(
            select(BloodBank).options(selectinload(BloodBank.facility), selectinload(BloodBank.manager_user))
        )
        blood_banks = result.scalars().all()
        return [
            BloodBankResponse.model_validate(bb, from_attributes=True)
            for bb in blood_banks
        ]
