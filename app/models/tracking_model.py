import uuid
from sqlalchemy import Column, String, ForeignKey, DateTime, Enum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base
from enum import Enum as PyEnum
from datetime import datetime

class TrackStateStatus(PyEnum):
    
    dispatched = "dispatched"
    pending_receive = "pending receive"
    received = "received"
    returned = "returned"
    rejected = "rejected"
    cancelled = "cancelled"

class TrackState(Base):
    __tablename__ = "track_states"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, index=True)
    
    # Foreign keys
    blood_distribution_id = Column(UUID(as_uuid=True), ForeignKey("blood_distributions.id", ondelete="CASCADE"), nullable=False)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Tracking details
    status = Column(Enum(TrackStateStatus), nullable=False)
    location = Column(String(255), nullable=True)  # GPS coordinates or facility name
    notes = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    blood_distribution = relationship("BloodDistribution", back_populates="track_states")
    created_by = relationship("User", foreign_keys=[created_by_id])

    def __str__(self):
        return f"{self.status} at {self.location or 'unknown location'} ({self.timestamp})"