import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Enum, func, Text, Boolean, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base
import enum


class RequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    fulfilled = "fulfilled"
    cancelled = "cancelled"  # New status for auto-cancelled requests


class BloodRequest(Base):
    """Model representing a request for blood or blood products."""

    __tablename__ = "blood_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    requester_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    fulfilled_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="SET NULL"))
    
    # Group ID to link related requests across multiple facilities
    request_group_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # Flag to indicate if this is the primary/master request
    is_master_request = Column(Boolean, default=False)

    blood_type = Column(String(10), nullable=False)
    blood_product = Column(String(50), nullable=False)
    quantity_requested = Column(Integer, nullable=False)
    status = Column(Enum(RequestStatus), default=RequestStatus.pending)
    notes = Column(Text, nullable=True)
    
    # Cancellation reason for auto-cancelled requests
    cancellation_reason = Column(String(200), nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    requester = relationship("User", foreign_keys=[requester_id])
    fulfilled_by = relationship("User", foreign_keys=[fulfilled_by_id])
    facility = relationship("Facility")
    option = Column(Enum("sent", "received", name="option"), server_default=text("'sent'"))
    
    def __repr__(self):
        return f"<BloodRequest(id={self.id}, requester_id={self.requester_id}, status={self.status}, group_id={self.request_group_id})>"