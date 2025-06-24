import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Enum, func, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base
import enum


class RequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    fulfilled = "fulfilled"


class BloodRequest(Base):
    """Model representing a request for blood or blood products."""

    __tablename__ = "blood_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    requester_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    fulfilled_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    blood_bank_id = Column(UUID(as_uuid=True), ForeignKey("blood_banks.id", ondelete="SET NULL"))
    # patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"))

    blood_type = Column(String(10), nullable=False)
    blood_product = Column(String(50), nullable=False)
    quantity_requested = Column(Integer, nullable=False)
    status = Column(Enum(RequestStatus), default=RequestStatus.pending)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    requester = relationship("User", foreign_keys=[requester_id])
    fulfilled_by = relationship("User", foreign_keys=[fulfilled_by_id])
    blood_bank = relationship("BloodBank")
    # patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)
    # patient = relationship("Patient", back_populates="blood_requests")
    
    def __repr__(self):
        return f"<BloodRequest(id={self.id}, requester_id={self.requester_id}, status={self.status})>"