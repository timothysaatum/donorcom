from pydantic import BaseModel, Field, field_validator
from uuid import UUID, uuid4
from datetime import datetime
from enum import Enum
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

class ProcessingStatus(str, Enum):

    pending = "pending"
    disptached = "dispatched"
    completed = "completed"

class PriorityStatus(str, Enum):

    urgent = "urgent"
    not_urgent = "not_urgent"

    @classmethod
    def _missing_(cls, value):
        if value == "not-urgent":
            return cls.not_urgent

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
    priority: Optional[str] = Field(None, description="Add request priority", example="urgent")

    @field_validator("facility_ids")
    def validate_facility_ids(cls, v):
        if len(v) != len(set(v)):
            raise ValueError("Duplicate facility IDs are not allowed")
        return v

class BloodRequestResponse(BaseModel):
    id: UUID
    requester_id: UUID
    requester_name: Optional[str] = Field(None, description="Name of the person making the request")
    facility_id: UUID
    receiving_facility_name: Optional[str] = Field(None, min_length=1, max_length=255)
    request_group_id: UUID
    blood_type: str
    blood_product: str
    quantity_requested: int
    request_status: Optional[RequestStatus] = None
    processing_status: Optional[ProcessingStatus] = None
    notes: Optional[str] = None
    priority: Optional[str] = None
    cancellation_reason: Optional[str] = None
   
    # Additional facility information
    requester_facility_name: Optional[str] = Field(None, description="Name of the facility making the request")

    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
    
    @classmethod
    def from_orm_with_facility_names(cls, blood_request):
        """Create response with facility names and requester name populated"""
    
        # Initialize with default value to ensure field is always set
        receiving_facility_name = "Unknown Facility"
    
        try:
            # Get receiving facility name (where request is sent to)
            if (blood_request.facility and 
            hasattr(blood_request.facility, 'facility_name') and 
            blood_request.facility.facility_name):
            
                facility_name = str(blood_request.facility.facility_name).strip()
                if facility_name:  # Check if not empty after stripping
                    receiving_facility_name = facility_name
        except (AttributeError, TypeError) as e:
            logger.warning(f"Error accessing facility name for request {getattr(blood_request, 'id', 'unknown')}: {e}")
            # receiving_facility_name remains "Unknown Facility"
        # Get requester's facility name (the facility making the request)
        requester_facility_name = None
        try:
            if blood_request.requester:
                # Try facility first (for administrators)
                if (hasattr(blood_request.requester, 'facility') and 
                    blood_request.requester.facility and
                    hasattr(blood_request.requester.facility, 'facility_name') and
                    blood_request.requester.facility.facility_name):
                    requester_facility_name = str(blood_request.requester.facility.facility_name).strip() or None
            
                # Try work_facility if facility didn't work (for staff/lab managers)
                elif (hasattr(blood_request.requester, 'work_facility') and 
                    blood_request.requester.work_facility and
                    hasattr(blood_request.requester.work_facility, 'facility_name') and
                    blood_request.requester.work_facility.facility_name):
                    requester_facility_name = str(blood_request.requester.work_facility.facility_name).strip() or None
                
        except (AttributeError, TypeError) as e:
            logger.warning(f"Error accessing requester facility name for request {getattr(blood_request, 'id', 'unknown')}: {e}")
    
        # Get requester's name
        requester_name = None
        try:
            if blood_request.requester:
                first_name = getattr(blood_request.requester, 'first_name', '') or ""
                last_name = getattr(blood_request.requester, 'last_name', '') or ""
            
                if first_name or last_name:
                    requester_name = f"{first_name} {last_name}".strip()
                    if not requester_name:  # Both were empty strings
                        requester_name = None
                else:
                    # Try alternative name fields
                    requester_name = (getattr(blood_request.requester, 'name', None) or 
                                getattr(blood_request.requester, 'username', None))
                
        except (AttributeError, TypeError) as e:
            logger.warning(f"Error accessing requester name for request {getattr(blood_request, 'id', 'unknown')}: {e}")
    
        # Ensure receiving_facility_name meets minimum length requirement
        if not receiving_facility_name or len(receiving_facility_name) < 1:
            receiving_facility_name = "Unknown Facility"
    
        # Create the response with all required fields, using getattr for safety
        try:
            return cls(
            id=getattr(blood_request, 'id', None),
            requester_id=getattr(blood_request, 'requester_id', None),
            facility_id=getattr(blood_request, 'facility_id', None),
            receiving_facility_name=receiving_facility_name,  # This is guaranteed to be valid
            request_group_id=getattr(blood_request, 'request_group_id', None),
            blood_type=getattr(blood_request, 'blood_type', ''),
            blood_product=getattr(blood_request, 'blood_product', ''),
            quantity_requested=getattr(blood_request, 'quantity_requested', 0),
            request_status=getattr(blood_request, 'request_status', None),
            processing_status=getattr(blood_request, 'processing_status', None),
            notes=getattr(blood_request, 'notes', None),
            priority=getattr(blood_request, 'priority', None),
            cancellation_reason=getattr(blood_request, 'cancellation_reason', None),
            requester_facility_name=requester_facility_name,
            requester_name=requester_name,
            created_at=getattr(blood_request, 'created_at', None),
            updated_at=getattr(blood_request, 'updated_at', None)
        )
        except Exception as e:
            # Log all the values for debugging
            logger.error(f"Error creating BloodRequestResponse for request {getattr(blood_request, 'id', 'unknown')}: {e}")
            logger.error(f"receiving_facility_name: '{receiving_facility_name}' (length: {len(receiving_facility_name)})")
            logger.error(f"blood_request attributes: {[attr for attr in dir(blood_request) if not attr.startswith('_')]}")
        
            # If all else fails, create a minimal valid response
        return cls(
            id=getattr(blood_request, 'id', uuid4()),
            requester_id=getattr(blood_request, 'requester_id', uuid4()),
            facility_id=getattr(blood_request, 'facility_id', uuid4()),
            receiving_facility_name="Unknown Facility",
            request_group_id=getattr(blood_request, 'request_group_id', uuid4()),
            blood_type=getattr(blood_request, 'blood_type', 'Unknown'),
            blood_product=getattr(blood_request, 'blood_product', 'Unknown'),
            quantity_requested=getattr(blood_request, 'quantity_requested', 0),
            request_status=getattr(blood_request, 'request_status', None),
            processing_status=getattr(blood_request, 'processing_status', None),
            notes=getattr(blood_request, 'notes', None),
            priority=getattr(blood_request, 'priority', None),
            cancellation_reason=getattr(blood_request, 'cancellation_reason', None),
            requester_facility_name=requester_facility_name,
            requester_name=requester_name,
            created_at=getattr(blood_request, 'created_at', datetime.now()),
            updated_at=getattr(blood_request, 'updated_at', datetime.now())
        )
            

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


class BloodRequestStatusUpdate(BaseModel):
    request_status: RequestStatus
    cancellation_reason: Optional[str] = None



class BloodRequestBulkCreateResponse(BaseModel):
    """Response for bulk request creation"""
    request_group_id: UUID
    total_requests_created: int
    requests: List[BloodRequestResponse]
    message: str
