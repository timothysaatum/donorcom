from pydantic import BaseModel, Field, UUID4
from typing import Optional
from datetime import datetime, date
from enum import Enum


class DistributionStatus(str, Enum):
    PENDING_RECEIVE = "pending receive"
    IN_TRANSIT = "in transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class BloodDistributionBase(BaseModel):
    blood_product: str = Field(
        ..., description="Type of blood product (e.g., Whole Blood, Plasma)"
    )
    blood_type: str = Field(..., description="Blood type (e.g., A+, B-, O+)")
    quantity: int = Field(..., ge=1, description="Units of blood being distributed")
    notes: Optional[str] = Field(None, description="Additional notes or instructions")
    batch_number: Optional[str] = Field(
        None, description="Batch number for inventory tracking"
    )
    expiry_date: Optional[date] = Field(
        None, description="Expiry date of the blood product"
    )
    temperature_maintained: Optional[bool] = Field(
        None, description="Whether proper temperature was maintained"
    )


class BloodDistributionCreate(BaseModel):
    """
    Create a blood distribution to fulfill a blood request.

    All distribution details (blood product, type, quantity, destination) are automatically
    pulled from the blood request to ensure data integrity and prevent mismatches.

    The request_id is provided as a path parameter in the URL.
    Optionally add notes for delivery instructions in the request body.

    Example:
    ```json
    {
      "notes": "Urgent delivery - patient in surgery"
    }
    ```
    Or send an empty body: {}
    """

    request_id: Optional[UUID4] = Field(
        None,
        description="ID of the blood request to fulfill. Typically provided as path parameter, not in body.",
    )
    notes: Optional[str] = Field(
        None,
        description="Optional delivery notes or special handling instructions",
    )


class BloodDistributionUpdate(BaseModel):
    status: Optional[DistributionStatus] = Field(
        None, description="Current status of the distribution"
    )
    notes: Optional[str] = Field(None, description="Additional notes or instructions")


class BloodDistributionResponse(BloodDistributionBase):
    id: UUID4
    blood_product_id: Optional[UUID4]
    request_id: Optional[UUID4]
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
