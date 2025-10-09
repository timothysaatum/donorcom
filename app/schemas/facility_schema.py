from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    field_validator,
    ConfigDict,
    StringConstraints,
)
from app.schemas.blood_bank_schema import BloodBankInFacilityResponse, BloodBankBase
from typing import Optional, Annotated
from datetime import datetime
from uuid import UUID


# --- Base Configuration for Performance ---
class BaseSchema(BaseModel):
    """Base schema with optimized configuration for performance"""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
        frozen=False,
        extra="forbid",
        from_attributes=True,
    )


class FacilityBase(BaseSchema):
    facility_name: Annotated[
        str, StringConstraints(min_length=3, max_length=155, strip_whitespace=True)
    ] = Field(..., description="Hospital/facility name")
    facility_email: EmailStr
    facility_contact_number: Annotated[
        str,
        StringConstraints(
            min_length=10,
            max_length=15,
            pattern=r"^\+?[\d\s\-\(\)]{10,15}$",
            strip_whitespace=True,
        ),
    ] = Field(..., description="Facility contact number")
    facility_digital_address: Annotated[
        str,
        StringConstraints(
            min_length=8,
            max_length=15,
            pattern=r"^[A-Z]{2}-\d{3,5}-\d{3,5}$",
            strip_whitespace=True,
        ),
    ] = Field(..., description="GPS digital address (e.g., GA-123-4567)")


class FacilityWithBloodBankCreate(FacilityBase):

    """Schema for creating a facility with its associated blood bank in one request"""

    blood_bank: Optional[BloodBankBase] = None


class FacilityUpdate(BaseSchema):
    facility_name: Optional[
        Annotated[
            str, StringConstraints(min_length=3, max_length=155, strip_whitespace=True)
        ]
    ] = None
    facility_email: Optional[EmailStr] = None
    facility_contact_number: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=10,
                max_length=15,
                pattern=r"^\+?[\d\s\-\(\)]{10,15}$",
                strip_whitespace=True,
            ),
        ]
    ] = None
    facility_digital_address: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=8,
                max_length=15,
                pattern=r"^[A-Z]{2}-\d{3,5}-\d{3,5}$",
                strip_whitespace=True,
            ),
        ]
    ] = None
    facility_manager_id: Optional[UUID] = None

    @field_validator("facility_digital_address")
    @classmethod
    def validate_gps_pattern(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith(
            ("GA-", "AS-", "BA-", "CP-", "EP-", "NP-", "UE-", "UW-", "TV-", "VR-", "XL-", "UK-")
        ):
            raise ValueError("Digital address must start with valid Ghana region code")
        return v


class FacilityResponse(BaseSchema):
    id: UUID
    facility_name: str
    facility_email: EmailStr
    facility_contact_number: Optional[str] = Field(..., min_length=10, max_length=14)
    facility_digital_address: str = Field(..., min_length=10, max_length=15)
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class FacilityWithBloodBank(FacilityResponse):
    blood_bank: Optional[BloodBankInFacilityResponse] = None
