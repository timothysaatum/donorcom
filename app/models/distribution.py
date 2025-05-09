import uuid
from sqlalchemy import Column, String, ForeignKey, DateTime, Enum, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base
from enum import Enum as PyEnum



class BloodDistributionStatus(PyEnum):
    pending = "pending"
    in_transit = "in_transit"
    delivered = "delivered"
    cancelled = "cancelled"


class BloodDistribution(Base):

    __tablename__ = "blood_distributions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, index=True)

    blood_product_id = Column(UUID(as_uuid=True), ForeignKey("blood_inventory.id", ondelete="SET NULL"), nullable=False)
    dispatched_to_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="SET NULL"), nullable=False)

    date_dispatched = Column(DateTime, nullable=False, server_default=func.now())
    quantity = Column(String(155), nullable=False)
    
    status = Column(
    Enum(BloodDistributionStatus, name="distribution_status"), 
    nullable=False, 
    default=BloodDistributionStatus.pending
    )
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    notes = Column(String(255), nullable=True)

    # Relationships
    blood_product = relationship("BloodInventory", backref="distributions")
    dispatched_to = relationship("Facility", backref="received_distributions")
    created_by = relationship("User", backref="created_distributions")

    def __str__(self):
        return f"Distribution {self.id} -> {self.dispatched_to.facility_name}"