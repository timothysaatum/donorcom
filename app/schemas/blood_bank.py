from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from uuid import UUID
from datetime import datetime

class BloodBankBase(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15)
    email: EmailStr
    blood_bank_name: str = Field(..., min_length=3, max_length=100)

class BloodBankCreate(BloodBankBase):
    facility_id: UUID
    manager_id: UUID

class BloodBankUpdate(BaseModel):
    phone: Optional[str] = Field(None, min_length=10, max_length=15)
    email: Optional[EmailStr] = None
    blood_bank_name: Optional[str] = Field(None, min_length=3, max_length=100)

class BloodBankResponse(BloodBankBase):
    id: UUID
    facility_id: UUID
    manager_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BloodBankInFacilityResponse(BaseModel):
    id: UUID
    phone: str
    email: EmailStr
    blood_bank_name: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
