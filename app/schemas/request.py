from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from datetime import datetime
from enum import Enum
from typing import List, Optional


class ProcessingStatus(str, Enum):

    pending = "pending"
    disptached = "dispatched"
    completed = "completed"


class RequestStatus(str, Enum):

    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
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

    @field_validator("facility_ids")
    def validate_facility_ids(cls, v):
        if len(v) != len(set(v)):
            raise ValueError("Duplicate facility IDs are not allowed")
        return v


class BloodRequestResponse(BaseModel):
    id: UUID
    requester_id: UUID
    facility_id: UUID
    receiving_facility_name: str = Field(..., min_length=1, max_length=255)  # Relaxed constraints
    request_group_id: UUID
    is_master_request: bool
    blood_type: str
    blood_product: str
    quantity_requested: int
    request_status: Optional[RequestStatus] = None
    processing_status: Optional[ProcessingStatus] = None
    notes: Optional[str] = None  # Make sure this is Optional
    option: Optional[str] = None  # Make sure this is Optional
    cancellation_reason: Optional[str] = None
    
    # Additional facility information
    requester_facility_name: Optional[str] = Field(None, description="Name of the facility making the request")
    
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_facility_names(cls, blood_request):
        """Create response with facility names populated"""
        
        # Get receiving facility name (where request is sent to)
        receiving_facility_name = "Unknown Facility"  # Default value
        if blood_request.facility:
            receiving_facility_name = blood_request.facility.facility_name or "Unknown Facility"
        
        # Ensure minimum length requirement is met
        if len(receiving_facility_name) < 1:
            receiving_facility_name = "Unknown Facility"

        # Get requester's facility name (the facility making the request)
        requester_facility_name = None
        if blood_request.requester:
            if blood_request.requester.facility:  # For facility administrators
                requester_facility_name = blood_request.requester.facility.facility_name
            elif blood_request.requester.work_facility:  # For staff/lab managers
                requester_facility_name = blood_request.requester.work_facility.facility_name
        
        # Create the response with all the original fields plus facility names
        return cls(
            id=blood_request.id,
            requester_id=blood_request.requester_id,
            facility_id=blood_request.facility_id,
            receiving_facility_name=receiving_facility_name,
            request_group_id=blood_request.request_group_id,
            is_master_request=blood_request.is_master_request,
            blood_type=blood_request.blood_type,
            blood_product=blood_request.blood_product,
            quantity_requested=blood_request.quantity_requested,
            request_status=blood_request.request_status,
            processing_status=blood_request.processing_status,
            notes=blood_request.notes,
            option=blood_request.option,
            cancellation_reason=blood_request.cancellation_reason,
            requester_facility_name=requester_facility_name,
            created_at=blood_request.created_at,
            updated_at=blood_request.updated_at
        )
        # Ensure all fields are populated correctly
        

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
    request_status: Optional[RequestStatus] = None


class BloodRequestBulkCreateResponse(BaseModel):
    """Response for bulk request creation"""
    request_group_id: UUID
    total_requests_created: int
    requests: List[BloodRequestResponse]
    message: str