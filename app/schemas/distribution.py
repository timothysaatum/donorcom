from pydantic import BaseModel, Field, UUID4
from typing import Optional
from datetime import datetime
from enum import Enum


class DistributionStatus(str, Enum):
    pending = "pending"
    in_transit = "in transit"
    delivered = "delivered"
    cancelled = "cancelled"
    returned = "returned"


class BloodDistributionBase(BaseModel):
    blood_product: str = Field(..., description="Type of blood product (e.g., Whole Blood, Plasma)")
    blood_type: str = Field(..., description="Blood type (e.g., A+, B-, O+)")
    quantity: int = Field(..., ge=1, description="Units of blood being distributed")
    notes: Optional[str] = Field(None, description="Additional notes or instructions")


class BloodDistributionCreate(BloodDistributionBase):
    blood_product_id: Optional[UUID4] = Field(None, description="ID of the specific blood inventory item")
    dispatched_to_id: UUID4 = Field(..., description="ID of the facility receiving the blood")
    # recipient_name: str = Field(..., description="name of patient")


class BloodDistributionUpdate(BaseModel):
    status: Optional[DistributionStatus] = Field(None, description="Current status of the distribution")
    date_delivered: Optional[datetime] = Field(None, description="Date and time when blood was delivered")
    tracking_number: Optional[str] = Field(None, description="Tracking number for shipment")
    notes: Optional[str] = Field(None, description="Additional notes or instructions")


class BloodDistributionResponse(BloodDistributionBase):
    id: UUID4
    blood_product_id: Optional[UUID4]
    dispatched_from_id: UUID4
    dispatched_to_id: UUID4
    created_by_id: Optional[UUID4]
    
    status: DistributionStatus
    date_dispatched: Optional[datetime]
    date_delivered: Optional[datetime]
    tracking_number: Optional[str]
    
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BloodDistributionDetailResponse(BloodDistributionResponse):
    dispatched_from_name: Optional[str] = None
    dispatched_to_name: Optional[str] = None
    created_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class DistributionStats(BaseModel):
    total_distributions: int
    pending_count: int
    in_transit_count: int
    delivered_count: int
    cancelled_count: int
    returned_count: int
    
    class Config:
        from_attributes = True