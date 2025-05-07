from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException
from uuid import UUID
from app.models.health_facility import Facility
from typing import Optional
from app.schemas.facility_schema import FacilityBase, FacilityResponse, FacilityUpdate
from sqlalchemy.orm import selectinload



class FacilityService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_facility(self, facility_data: FacilityBase, facility_manager_id: UUID) -> FacilityResponse:
        
        # Check for duplicate facility email
        result = await self.db.execute(
            select(Facility).where(Facility.facility_email == facility_data.facility_email)
        )

        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Facility with this email already exists")

        # Build the Facility instance, excluding manager fields from the payload
        new_facility = Facility(
            **facility_data.model_dump(exclude={"facility_manager", "facility_manager_id"}),
            facility_manager_id=facility_manager_id
        )

        self.db.add(new_facility)
        await self.db.commit()
        await self.db.refresh(new_facility)

        # Load the manager relationship for response
        await self.db.refresh(new_facility, attribute_names=["facility_manager"])

        return new_facility

    async def get_facility(self, facility_id: UUID) -> Optional[Facility]:
        result = await self.db.execute(
            select(Facility).where(Facility.id == facility_id)
        )

        return result.scalar_one_or_none()

    async def update_facility(self, facility_id: UUID, facility_data: FacilityUpdate) -> FacilityResponse:
        
        facility = await self.get_facility(facility_id)

        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")

        update_data = facility_data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(facility, field, value)

        await self.db.commit()
        await self.db.refresh(facility)

        return facility


    async def delete_facility(self, facility_id: UUID) -> bool:
        facility = await self.get_facility(facility_id)
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")

        await self.db.delete(facility)
        await self.db.commit()
        return True

    async def get_all_facilities(self) -> list[FacilityResponse]:
        result = await self.db.execute(
        select(Facility).options(selectinload(Facility.facility_manager)))
        facilities = result.scalars().all()
        return [
            FacilityResponse.model_validate(facility, from_attributes=True)
            for facility in facilities
        ]
