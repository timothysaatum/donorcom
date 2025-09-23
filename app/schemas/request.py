from pydantic import BaseModel, Field, field_validator, ConfigDict, StringConstraints
from uuid import UUID, uuid4
from datetime import datetime
from enum import Enum
from typing import List, Optional, Annotated
import logging

logger = logging.getLogger(__name__)


# --- Base Configuration for Performance ---
class BaseSchema(BaseModel):
    """Base schema with optimized configuration for performance"""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
        frozen=False,
        extra="forbid",
        from_attributes=True,
    )


class ProcessingStatus(str, Enum):

    PENDING = "pending"
    INITIATED = "initiated"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"


class PriorityStatus(str, Enum):

    URGENT = "urgent"
    NOT_URGENT = "not_urgent"

    @classmethod
    def _missing_(cls, value):
        if value == "not-urgent":
            return cls.NOT_URGENT


class RequestStatus(str, Enum):

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class RequestDirection(str, Enum):
    """Enum for request direction filtering"""

    RECEIVED = "received"
    SENT = "sent"
    ALL = "all"


class BloodRequestCreate(BaseSchema):
    blood_type: Annotated[
        str, StringConstraints(pattern=r"^(A|B|AB|O)[+-]$", strip_whitespace=True)
    ] = Field(..., description="Blood type (e.g., A+, B-, O+, AB-)")
    blood_product: Annotated[
        str, StringConstraints(min_length=2, max_length=50, strip_whitespace=True)
    ] = Field(..., description="Type of blood product needed")
    quantity_requested: int = Field(
        ..., gt=0, le=100, description="Number of units requested (1-100)"
    )
    facility_ids: List[UUID] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="List of facility IDs to send request to",
    )
    notes: Optional[Annotated[str, StringConstraints(max_length=500)]] = Field(
        None, description="Additional notes or requirements"
    )
    priority: Optional[str] = Field(
        "not_urgent", description="Request priority", pattern=r"^(urgent|not_urgent)$"
    )

    @field_validator("facility_ids")
    def validate_facility_ids(cls, v):
        if len(v) != len(set(v)):
            raise ValueError("Duplicate facility IDs are not allowed")
        return v


class BloodRequestResponse(BaseModel):
    id: UUID
    requester_id: UUID
    requester_name: Optional[str] = Field(
        None, description="Name of the person making the request"
    )
    facility_id: UUID
    source_facility_id: UUID
    receiving_facility_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Name of the target/receiving facility",
    )
    source_facility_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Name of the source/originating facility",
    )
    request_group_id: UUID
    blood_type: str
    blood_product: str
    quantity_requested: int
    request_status: Optional[RequestStatus] = None
    processing_status: Optional[ProcessingStatus] = None
    notes: Optional[str] = None
    priority: Optional[str] = None
    cancellation_reason: Optional[str] = None

    # Additional facility information (deprecated - use source_facility_name)
    requester_facility_name: Optional[str] = Field(
        None,
        description="Name of the facility making the request (deprecated - use source_facility_name)",
    )

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_facility_names(cls, blood_request):
        """Create response with facility names and requester name populated"""

        # Initialize with default values
        receiving_facility_name = "Unknown Facility"
        source_facility_name = "Unknown Facility"

        try:
            # Get receiving facility name (target facility - where request is sent to)
            if (
                hasattr(blood_request, "target_facility")
                and blood_request.target_facility
                and hasattr(blood_request.target_facility, "facility_name")
                and blood_request.target_facility.facility_name
            ):

                facility_name = str(blood_request.target_facility.facility_name).strip()
                if facility_name:  # Check if not empty after stripping
                    receiving_facility_name = facility_name

        except (AttributeError, TypeError) as e:
            logger.warning(
                f"Error accessing target facility name for request {getattr(blood_request, 'id', 'unknown')}: {e}"
            )

        try:
            # Get source facility name (originating facility - where request comes from)
            if (
                hasattr(blood_request, "source_facility")
                and blood_request.source_facility
                and hasattr(blood_request.source_facility, "facility_name")
                and blood_request.source_facility.facility_name
            ):

                facility_name = str(blood_request.source_facility.facility_name).strip()
                if facility_name:
                    source_facility_name = facility_name

        except (AttributeError, TypeError) as e:
            logger.warning(
                f"Error accessing source facility name for request {getattr(blood_request, 'id', 'unknown')}: {e}"
            )

        # Get requester's facility name (DEPRECATED - use source_facility_name)
        requester_facility_name = (
            source_facility_name  # Use the explicit source facility name
        )

        # Get requester's name
        requester_name = None
        try:
            if blood_request.requester:
                first_name = getattr(blood_request.requester, "first_name", "") or ""
                last_name = getattr(blood_request.requester, "last_name", "") or ""

                if first_name or last_name:
                    requester_name = f"{first_name} {last_name}".strip()
                    if not requester_name:  # Both were empty strings
                        requester_name = None
                else:
                    # Try alternative name fields
                    requester_name = getattr(
                        blood_request.requester, "name", None
                    ) or getattr(blood_request.requester, "username", None)

        except (AttributeError, TypeError) as e:
            logger.warning(
                f"Error accessing requester name for request {getattr(blood_request, 'id', 'unknown')}: {e}"
            )

        # Ensure facility names meet minimum length requirement
        if not receiving_facility_name or len(receiving_facility_name) < 1:
            receiving_facility_name = "Unknown Facility"
        if not source_facility_name or len(source_facility_name) < 1:
            source_facility_name = "Unknown Facility"

        # Create the response with all required fields, using getattr for safety
        try:
            return cls(
                id=getattr(blood_request, "id", None),
                requester_id=getattr(blood_request, "requester_id", None),
                facility_id=getattr(blood_request, "facility_id", None),
                source_facility_id=getattr(blood_request, "source_facility_id", None),
                receiving_facility_name=receiving_facility_name,
                source_facility_name=source_facility_name,
                request_group_id=getattr(blood_request, "request_group_id", None),
                blood_type=getattr(blood_request, "blood_type", ""),
                blood_product=getattr(blood_request, "blood_product", ""),
                quantity_requested=getattr(blood_request, "quantity_requested", 0),
                request_status=getattr(blood_request, "request_status", None),
                processing_status=getattr(blood_request, "processing_status", None),
                notes=getattr(blood_request, "notes", None),
                priority=getattr(blood_request, "priority", None),
                cancellation_reason=getattr(blood_request, "cancellation_reason", None),
                requester_facility_name=requester_facility_name,  # Deprecated
                requester_name=requester_name,
                created_at=getattr(blood_request, "created_at", None),
                updated_at=getattr(blood_request, "updated_at", None),
            )
        except Exception as e:
            # Log all the values for debugging
            logger.error(
                f"Error creating BloodRequestResponse for request {getattr(blood_request, 'id', 'unknown')}: {e}"
            )
            logger.error(
                f"receiving_facility_name: '{receiving_facility_name}' (length: {len(receiving_facility_name)})"
            )
            logger.error(
                f"source_facility_name: '{source_facility_name}' (length: {len(source_facility_name)})"
            )
            logger.error(
                f"blood_request attributes: {[attr for attr in dir(blood_request) if not attr.startswith('_')]}"
            )

            # If all else fails, create a minimal valid response
            return cls(
                id=getattr(blood_request, "id", uuid4()),
                requester_id=getattr(blood_request, "requester_id", uuid4()),
                facility_id=getattr(blood_request, "facility_id", uuid4()),
                source_facility_id=getattr(
                    blood_request, "source_facility_id", uuid4()
                ),
                receiving_facility_name="Unknown Facility",
                source_facility_name="Unknown Facility",
                request_group_id=getattr(blood_request, "request_group_id", uuid4()),
                blood_type=getattr(blood_request, "blood_type", "Unknown"),
                blood_product=getattr(blood_request, "blood_product", "Unknown"),
                quantity_requested=getattr(blood_request, "quantity_requested", 0),
                request_status=getattr(blood_request, "request_status", None),
                processing_status=getattr(blood_request, "processing_status", None),
                notes=getattr(blood_request, "notes", None),
                priority=getattr(blood_request, "priority", None),
                cancellation_reason=getattr(blood_request, "cancellation_reason", None),
                requester_facility_name="Unknown Facility",
                requester_name=None,
                created_at=getattr(blood_request, "created_at", None),
                updated_at=getattr(blood_request, "updated_at", None),
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
    processing_status: Optional[ProcessingStatus] = None
    cancellation_reason: Optional[str] = None


class BloodRequestBulkCreateResponse(BaseModel):
    """Response for bulk request creation"""

    request_group_id: UUID
    total_requests_created: int
    requests: List[BloodRequestResponse]
    message: str
