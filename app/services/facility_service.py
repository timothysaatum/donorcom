from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException
from uuid import UUID
from app.models.health_facility import Facility
from app.models.blood_bank import BloodBank
from typing import Optional, Union
from app.schemas.facility_schema import (
    FacilityBase,
    FacilityResponse,
    FacilityUpdate,
    FacilityWithBloodBankCreate,
    FacilityWithBloodBank,
)
from sqlalchemy.orm import selectinload


class FacilityService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_facility(
        self, facility_data: FacilityBase, facility_manager_id: UUID
    ) -> FacilityResponse:

        # Check for duplicate facility email
        result = await self.db.execute(
            select(Facility).where(
                Facility.facility_email == facility_data.facility_email
            )
        )

        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=400, detail="Facility with this email already exists"
            )

        # Build the Facility instance, excluding manager fields from the payload
        new_facility = Facility(
            **facility_data.model_dump(
                exclude={"facility_manager", "facility_manager_id"}
            ),
            facility_manager_id=facility_manager_id
        )

        self.db.add(new_facility)
        await self.db.commit()
        await self.db.refresh(new_facility)

        # Load the manager relationship for response
        await self.db.refresh(new_facility, attribute_names=["facility_manager"])

        return new_facility

    async def create_facility_with_blood_bank(
        self, facility_data: FacilityWithBloodBankCreate, facility_manager_id: UUID
    ) -> Union[FacilityResponse, FacilityWithBloodBank]:
        """Create a facility and optionally its associated blood bank"""

        # Check for duplicate facility email
        result = await self.db.execute(
            select(Facility).where(
                Facility.facility_email == facility_data.facility_email
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=400, detail="Facility with this email already exists"
            )

        # Store blood_bank_data BEFORE any overwrites
        blood_bank_data = facility_data.blood_bank

        # If blood bank data is provided, check for duplicate
        if blood_bank_data:
            result = await self.db.execute(
                select(BloodBank).where(BloodBank.email == blood_bank_data.email)
            )
            if result.scalar_one_or_none():
                raise HTTPException(
                    status_code=400, detail="Blood bank with this email already exists"
                )

        # Create facility
        new_facility = Facility(
            facility_name=facility_data.facility_name,
            facility_email=facility_data.facility_email,
            facility_contact_number=facility_data.facility_contact_number,
            facility_digital_address=facility_data.facility_digital_address,
            facility_manager_id=facility_manager_id,
        )

        self.db.add(new_facility)
        await self.db.flush()

        blood_bank = None

        # Create blood bank if data was provided
        if blood_bank_data:
            blood_bank = BloodBank(
                **blood_bank_data.model_dump(),
                facility_id=new_facility.id,
                manager_id=facility_manager_id
            )
            self.db.add(blood_bank)

        await self.db.commit()

        # Refresh with relationships loaded
        await self.db.refresh(new_facility)
        if blood_bank:
            await self.db.refresh(blood_bank)

        # Load relationships
        result = await self.db.execute(
            select(Facility)
            .options(
                selectinload(Facility.facility_manager),
                selectinload(Facility.blood_bank),
            )
            .where(Facility.id == new_facility.id)
        )

        facility_with_relations = result.scalar_one()

        # Return appropriate response
        if blood_bank_data:
            return FacilityWithBloodBank.model_validate(
                facility_with_relations, from_attributes=True
            )
        else:
            return FacilityResponse.model_validate(
                facility_with_relations, from_attributes=True
            )

    async def get_facility(self, facility_id: UUID) -> Optional[Facility]:
        result = await self.db.execute(
            select(Facility).where(Facility.id == facility_id)
        )

        return result.scalar_one_or_none()

    async def update_facility(
        self, facility_id: UUID, facility_data: FacilityUpdate
    ) -> FacilityResponse:

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
            select(Facility).options(selectinload(Facility.facility_manager))
        )
        facilities = result.scalars().all()
        return [
            FacilityResponse.model_validate(facility, from_attributes=True)
            for facility in facilities
        ]
