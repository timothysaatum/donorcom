import uuid
from sqlalchemy import Column, String, ForeignKey, DateTime, Enum, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base
from enum import Enum as PyEnum


class BloodDistributionStatus(PyEnum):
    pending = "pending"
    in_transit = "in transit"
    delivered = "delivered"
    cancelled = "cancelled"
    returned = "returned"  # Added for cases where blood is returned to inventory


class BloodDistribution(Base):
    __tablename__ = "blood_distributions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, index=True)
    
    # Foreign keys
    blood_product_id = Column(UUID(as_uuid=True), ForeignKey("blood_inventory.id", ondelete="SET NULL"), nullable=True)
    dispatched_from_id = Column(UUID(as_uuid=True), ForeignKey("blood_banks.id", ondelete="SET NULL"), nullable=False)
    dispatched_to_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="SET NULL"), nullable=False)
    # track_state_id = Column(UUID(as_uuid=True), ForeignKey("track_state.id", ondelete="SET NULL"), nullable=False)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Distribution details
    blood_product = Column(String(50), nullable=False)  # e.g., "Whole Blood", "Plasma", "Platelets"
    blood_type = Column(String(10), nullable=False)     # e.g., "A+", "B-", "O+", "AB-"
    quantity = Column(Integer, nullable=False)          # Units of blood
    recipient_name = Column(String(200), nullable=False)
    
    # Tracking details
    status = Column(
        Enum(BloodDistributionStatus, name="distribution_status"), 
        nullable=False, 
        default=BloodDistributionStatus.pending
    )
    date_dispatched = Column(DateTime, nullable=True)
    date_delivered = Column(DateTime, nullable=True)
    tracking_number = Column(String(100), nullable=True)

    # Administrative
    notes = Column(String(500), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    inventory_item = relationship("BloodInventory", foreign_keys=[blood_product_id], backref="distributions")
    dispatched_from = relationship("BloodBank", foreign_keys=[dispatched_from_id], backref="outgoing_distributions")
    dispatched_to = relationship("Facility", foreign_keys=[dispatched_to_id], backref="incoming_distributions")
    created_by = relationship("User", foreign_keys=[created_by_id], backref="created_distributions")

    # track_state = relationship("TrackState", foreign_keys=[track_state_id], backref="distribution")
    track_states = relationship("TrackState", back_populates="blood_distribution", cascade="all, delete-orphan")


    def __str__(self):
        return f"{self.blood_product} ({self.blood_type}) → {self.dispatched_to.facility_name}"