from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict, ValidationInfo
from app.schemas.blood_bank import BloodBankInFacilityResponse
from typing import Optional
from datetime import datetime
from uuid import UUID
import re



class FacilityBase(BaseModel):

    facility_name: str = Field(..., min_length=5, max_length=155)
    facility_email: EmailStr
    facility_contact_number: Optional[str] = Field(..., min_length=10, max_length=14)
    facility_digital_address: str = Field(..., min_length=10, max_length=15)
    

    @field_validator("facility_digital_address")
    def match_gps_pattern(cls, v: str, values: ValidationInfo) -> str:
        gps_pattern = re.compile(r"^[A-Z]{2}-\d{3,5}-\d{3,5}$")
        if not gps_pattern.match(v):
            raise ValueError("Invalid digital address format. Expected format: 'GA-123-4567'")
        return v

    model_config = ConfigDict(from_attributes=True)


class FacilityUpdate(BaseModel):
    facility_name: Optional[str] = Field(None, min_length=5, max_length=155)
    facility_email: Optional[EmailStr] = None
    facility_contact_number: Optional[str] = Field(None, min_length=10, max_length=14)
    facility_digital_address: Optional[str] = Field(None, min_length=10, max_length=15)
    facility_manager_id: Optional[UUID] = None

    @field_validator("facility_digital_address")
    def match_gps_pattern(cls, v: str, values: ValidationInfo) -> str:

        if v is not None:
            gps_pattern = re.compile(r"^[A-Z]{2}-\d{3,5}-\d{3,5}$")

            if not gps_pattern.match(v):
                raise ValueError("Invalid digital address format. Expected format: 'GA-123-4567'")

        return v

    model_config = ConfigDict(from_attributes=True)


class FacilityResponse(BaseModel):

    id: UUID
    facility_name: str = Field(..., min_length=5, max_length=155)
    facility_email: EmailStr
    facility_contact_number: Optional[str] = Field(..., min_length=10, max_length=14)
    facility_digital_address: str = Field(..., min_length=10, max_length=15)
    created_at: datetime
    blood_bank: Optional[BloodBankInFacilityResponse] = None
    model_config = ConfigDict(from_attributes=True)
