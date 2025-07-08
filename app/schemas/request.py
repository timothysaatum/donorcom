# from pydantic import BaseModel
# from uuid import UUID
# from datetime import datetime
# from enum import Enum


# class RequestStatus(str, Enum):
#     pending = "pending"
#     approved = "approved"
#     rejected = "rejected"
#     fulfilled = "fulfilled"


# class BloodRequestCreate(BaseModel):
#     blood_type: str
#     blood_product: str
#     quantity_requested: int
#     blood_bank_id: UUID
#     # patient_id: UUID | None = None
#     notes: str | None = None


# class BloodRequestResponse(BloodRequestCreate):
#     id: UUID
#     requester_id: UUID
#     status: RequestStatus
#     created_at: datetime
#     updated_at: datetime

#     class Config:
#         from_attributes = True

        
# class BloodRequestUpdate(BaseModel):
#     blood_type: str | None = None
#     blood_product: str | None = None
#     quantity_requested: int | None = None
#     blood_bank_id: UUID | None = None
#     # patient_id: UUID | None = None
#     notes: str | None = None
#     status: RequestStatus | None = None
from pydantic import BaseModel, Field, validator
from uuid import UUID
from datetime import datetime
from enum import Enum
from typing import List, Optional


class RequestStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    fulfilled = "fulfilled"
    cancelled = "cancelled"

class RequestDirection(str, Enum):
    """Enum for request direction filtering"""
    RECEIVED = "received"
    SENT = "sent"
    ALL = "all"

class BloodRequestCreate(BaseModel):
    blood_type: str = Field(..., description="Blood type (e.g., A+, B-, O+, AB-)")
    blood_product: str = Field(..., description="Type of blood product needed")
    quantity_requested: int = Field(..., gt=0, description="Quantity of blood product needed")
    facility_ids: List[UUID] = Field(..., min_items=1, max_items=10, description="List of facility IDs to send request to")
    notes: Optional[str] = Field(None, description="Additional notes or requirements")

    @validator('facility_ids')
    def validate_facility_ids(cls, v):
        if len(v) != len(set(v)):
            raise ValueError('Duplicate facility IDs are not allowed')
        return v


class BloodRequestResponse(BaseModel):
    id: UUID
    requester_id: UUID
    facility_id: UUID
    request_group_id: UUID
    is_master_request: bool
    blood_type: str
    blood_product: str
    quantity_requested: int
    status: RequestStatus
    notes: Optional[str]
    option: Optional[str]
    cancellation_reason: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BloodRequestGroupResponse(BaseModel):
    """Response model for grouped requests"""
    request_group_id: UUID
    blood_type: str
    blood_product: str
    quantity_requested: int
    notes: Optional[str]
    master_request: BloodRequestResponse
    related_requests: List[BloodRequestResponse]
    total_facilities: int
    pending_count: int
    approved_count: int
    rejected_count: int
    fulfilled_count: int
    cancelled_count: int
    created_at: datetime
    updated_at: datetime


class BloodRequestUpdate(BaseModel):
    blood_type: Optional[str] = None
    blood_product: Optional[str] = None
    quantity_requested: Optional[int] = Field(None, gt=0)
    notes: Optional[str] = None
    status: Optional[RequestStatus] = None


class BloodRequestBulkCreateResponse(BaseModel):
    """Response for bulk request creation"""
    request_group_id: UUID
    total_requests_created: int
    requests: List[BloodRequestResponse]
    message: str