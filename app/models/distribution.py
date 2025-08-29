import uuid
from typing import Optional
from sqlalchemy import String, ForeignKey, DateTime, Enum, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from enum import Enum as PyEnum


class BloodDistributionStatus(PyEnum):
    pending_receive = "pending recieve"  # Initial status when distribution is created
    in_transit = "in transit"            # When blood is being transported
    returned = "returned"                # Added for cases where blood is returned to inventory


class BloodDistribution(Base):
    __tablename__ = "blood_distributions"

    # --- Columns ---
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    blood_product: Mapped[str] = mapped_column(String(50), nullable=False)
    blood_type: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[BloodDistributionStatus] = mapped_column(
        Enum(BloodDistributionStatus, name="distribution_status"),
        nullable=False,
        default=BloodDistributionStatus.pending_receive,
    )
    
    date_dispatched: Mapped[Optional[DateTime]] = mapped_column(DateTime, nullable=True)
    date_delivered: Mapped[Optional[DateTime]] = mapped_column(DateTime, nullable=True)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # --- Relationships ---
    blood_product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("blood_inventory.id", ondelete="SET NULL"),
        nullable=True,
    )
    dispatched_from_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("blood_banks.id", ondelete="CASCADE"),
        nullable=False,
    )
    dispatched_to_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    inventory_item = relationship("BloodInventory", foreign_keys=[blood_product_id], back_populates="distributions")
    dispatched_from = relationship("BloodBank", foreign_keys=[dispatched_from_id], back_populates="outgoing_distributions")
    dispatched_to = relationship("Facility", foreign_keys=[dispatched_to_id], back_populates="incoming_distributions")
    created_by = relationship("User", foreign_keys=[created_by_id])
    track_states = relationship(
        "TrackState", 
        back_populates="blood_distribution", 
        cascade="all, delete-orphan",
    )

    # --- Methods ---
    def __str__(self) -> str:
        return f"{self.blood_product} ({self.blood_type}) → {self.dispatched_to.facility_name}"
