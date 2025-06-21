from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from enum import Enum


class RequestStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    fulfilled = "fulfilled"


class BloodRequestCreate(BaseModel):
    blood_type: str
    blood_product: str
    quantity_requested: int
    blood_bank_id: UUID
    # patient_id: UUID | None = None
    notes: str | None = None


class BloodRequestResponse(BloodRequestCreate):
    id: UUID
    requester_id: UUID
    status: RequestStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

        
class BloodRequestUpdate(BaseModel):
    blood_type: str | None = None
    blood_product: str | None = None
    quantity_requested: int | None = None
    blood_bank_id: UUID | None = None
    # patient_id: UUID | None = None
    notes: str | None = None
    status: RequestStatus | None = None