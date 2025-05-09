from pydantic import BaseModel, UUID4, Field
from typing import Optional
from datetime import datetime


class BloodDistributionBase(BaseModel):
    blood_product_id: UUID4
    quantity: str
    status: Optional[str] = Field(default="pending", description="Status of the distribution")
    notes: Optional[str] = None


class BloodDistributionCreate(BloodDistributionBase):
    pass


class BloodDistributionUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    quantity: Optional[str] = None


class BloodDistributionResponse(BloodDistributionBase):
    id: UUID4
    dispatched_to_id: UUID4
    created_by_id: UUID4
    date_dispatched: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
