from pydantic import BaseModel, Field, UUID4
from typing import Optional
from datetime import datetime
from enum import Enum

class TrackStateStatus(str, Enum):

    dispatched = "dispatched"
    pending_receive = "pending receive"
    received = "received"
    returned = "returned"
    rejected = "rejected"
    cancelled = "cancelled"


class TrackStateBase(BaseModel):

    status: TrackStateStatus = Field(..., description="Current state of the tracking")
    location: Optional[str] = Field(None, description="GPS coordinates or facility name")
    notes: Optional[str] = Field(None, description="Additional notes about this state")


class TrackStateCreate(TrackStateBase):

    blood_distribution_id: UUID4 = Field(..., description="ID of the blood distribution being tracked")


class TrackStateResponse(TrackStateBase):

    id: UUID4
    blood_distribution_id: UUID4
    created_by_id: Optional[UUID4]
    timestamp: datetime
    
    class Config:
        from_attributes = True


class TrackStateDetailResponse(TrackStateResponse):

    created_by_name: Optional[str] = None
    class Config:
        from_attributes = True
