from pydantic import BaseModel, Field, UUID4
from typing import Optional
from datetime import date, datetime


class BloodInventoryBase(BaseModel):
    blood_product: str = Field(..., description="Type of blood product (e.g., Whole Blood, Plasma)")
    blood_type: str = Field(..., description="Blood type (e.g., A+, B-, O+)")
    quantity: int = Field(..., ge=0, description="Units of blood available")
    expiry_date: date = Field(..., description="Expiration date of the blood unit")


class BloodInventoryCreate(BloodInventoryBase):
    pass


class BloodInventoryUpdate(BaseModel):
    blood_product: Optional[str] = None
    blood_type: Optional[str] = None
    quantity: Optional[int] = Field(None, ge=0)
    expiry_date: Optional[date] = None


class BloodInventoryResponse(BloodInventoryBase):
    id: UUID4
    blood_bank_id: UUID4
    added_by_id: Optional[UUID4]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BloodInventoryDetailResponse(BloodInventoryResponse):
    # Optional: Include nested data about blood bank and user who added
    blood_bank_name: Optional[str] = None
    added_by_name: Optional[str] = None

    class Config:
        from_attributes = True