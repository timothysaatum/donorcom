from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from fastapi import HTTPException
from uuid import UUID
from typing import List, Optional
from app.models.patient import Patient
from app.schemas.patient import PatientCreate, PatientUpdate


class PatientService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_patient(self, data: PatientCreate) -> Patient:
        new_patient = Patient(**data.model_dump())
        self.db.add(new_patient)
        await self.db.commit()
        await self.db.refresh(new_patient)
        return new_patient

    async def get_patient(self, patient_id: UUID) -> Optional[Patient]:
        result = await self.db.execute(select(Patient).where(Patient.id == patient_id))
        return result.scalar_one_or_none()

    async def update_patient(self, patient_id: UUID, data: PatientUpdate) -> Patient:
        patient = await self.get_patient(patient_id)
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(patient, field, value)
        await self.db.commit()
        await self.db.refresh(patient)
        return patient

    async def delete_patient(self, patient_id: UUID) -> None:
        patient = await self.get_patient(patient_id)
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        await self.db.delete(patient)
        await self.db.commit()

    async def list_patients(self) -> List[Patient]:
        result = await self.db.execute(select(Patient).order_by(Patient.created_at.desc()))
        return result.scalars().all()