from pydantic import BaseModel, Field, UUID4
from typing import Optional
from datetime import datetime
from enum import Enum

class TrackStateStatus(str, Enum):
    DISPATCHED = "dispatched"
    PENDING_RECEIVE = "pending receive"
    RECEIVED = "received"
    RETURNED = "returned"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class TrackStateBase(BaseModel):
    status: TrackStateStatus = Field(..., description="Current state of the tracking")
    location: Optional[str] = Field(None, description="GPS coordinates or facility name")
    notes: Optional[str] = Field(None, description="Additional notes about this state")


class TrackStateCreate(TrackStateBase):
    blood_distribution_id: Optional[UUID4] = Field(None, description="ID of the blood distribution being tracked")
    blood_request_id: Optional[UUID4] = Field(..., description="ID of the blood request being tracked")


class TrackStateResponse(TrackStateBase):
    id: UUID4
    blood_distribution_id: Optional[UUID4] = Field(None, description="ID of the blood distribution (optional)")
    blood_request_id: UUID4 = Field(..., description="ID of the blood request being tracked")
    created_by_id: UUID4
    timestamp: datetime
    
    class Config:
        from_attributes = True


class TrackStateDetailResponse(TrackStateResponse):
    created_by_name: Optional[str] = None
    
    class Config:
        from_attributes = True