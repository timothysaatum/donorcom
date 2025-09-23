import uuid
from typing import Optional
from sqlalchemy import (
    Date,
    String,
    Integer,
    DateTime,
    ForeignKey,
    Enum,
    func,
    Text,
    Boolean,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from app.db.base import Base
from app.schemas.distribution import DistributionStatus
from app.schemas.request import PriorityStatus, ProcessingStatus, RequestStatus


class BloodRequest(Base):
    """Model representing a request for blood or blood products."""

    __tablename__ = "blood_requests"

    # --- Columns ---
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    request_group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    is_master_request: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    blood_type: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    blood_product: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    quantity_requested: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    request_status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus),
        default=RequestStatus.PENDING,
        index=True,
    )
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus),
        default=ProcessingStatus.PENDING,
        index=True,
    )
    priority: Mapped[Optional[PriorityStatus]] = mapped_column(
        Enum(PriorityStatus),
        nullable=True,
        default=PriorityStatus.NOT_URGENT,
        index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    option: Mapped[str] = mapped_column(String(10), default="sent")

    created_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), index=True
    )

    # --- Relationships ---
    requester_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    fulfilled_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Target/receiving facility for the request",
    )
    source_facility_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Source/originating facility for the request",
    )

    requester = relationship("User", foreign_keys=[requester_id])
    fulfilled_by = relationship("User", foreign_keys=[fulfilled_by_id])
    target_facility = relationship(
        "Facility", foreign_keys=[facility_id], back_populates="received_blood_requests"
    )
    source_facility = relationship(
        "Facility",
        foreign_keys=[source_facility_id],
        back_populates="sent_blood_requests",
    )
    distributions = relationship(
        "BloodDistribution",
        back_populates="blood_request",
        cascade="all, delete-orphan",
    )
    track_states = relationship(
        "TrackState",
        back_populates="blood_request",
        cascade="all, delete-orphan",
    )

    # --- Validation Methods ---
    @validates("quantity_requested")
    def validate_quantity_requested(self, key, value):
        """Validate that requested quantity is positive."""
        if value <= 0:
            raise ValueError("Requested quantity must be greater than 0")
        return value

    @validates("request_status", "processing_status")
    def validate_status_consistency(self, key, value):
        """Ensure status consistency between request and processing status."""
        # If request is cancelled or rejected, processing should be reset to pending
        if key == "request_status":
            if value in [RequestStatus.CANCELLED, RequestStatus.REJECTED]:
                # This will be handled by the caller to also update processing_status
                pass
        return value

    # --- Methods ---
    @property
    def total_distributed_quantity(self) -> int:
        """Calculate total quantity distributed for this request."""
        return sum(
            dist.quantity
            for dist in self.distributions
            if dist.status != DistributionStatus.CANCELLED
        )

    @property
    def remaining_quantity(self) -> int:
        """Calculate remaining quantity to be distributed."""
        return max(0, self.quantity_requested - self.total_distributed_quantity)

    @property
    def is_fully_distributed(self) -> bool:
        """Check if the request has been fully distributed."""
        return self.remaining_quantity == 0

    @property
    def has_active_distributions(self) -> bool:
        """Check if there are any active (non-cancelled, non-returned) distributions."""
        active_statuses = {
            DistributionStatus.PENDING_RECEIVE,
            DistributionStatus.IN_TRANSIT,
            DistributionStatus.DELIVERED,
        }
        return any(dist.status in active_statuses for dist in self.distributions)

    @property
    def latest_distribution(self):
        """Get the most recently created distribution for this request."""
        if not self.distributions:
            return None
        return max(self.distributions, key=lambda d: d.created_at)

    @property
    def can_be_cancelled(self) -> bool:
        """Check if the request can be cancelled (no delivered distributions)."""
        delivered_distributions = [
            dist
            for dist in self.distributions
            if dist.status == DistributionStatus.DELIVERED
        ]
        return len(delivered_distributions) == 0

    def get_distributions_by_status(self, status: DistributionStatus):
        """Get all distributions with a specific status."""
        return [dist for dist in self.distributions if dist.status == status]

    def calculate_fulfillment_percentage(self) -> float:
        """Calculate what percentage of the request has been fulfilled."""
        if self.quantity_requested == 0:
            return 0.0
        return (self.total_distributed_quantity / self.quantity_requested) * 100

    def is_urgent_and_unfulfilled(self) -> bool:
        """Check if this is an urgent request that hasn't been fully fulfilled."""
        return (
            self.priority == PriorityStatus.URGENT
            and not self.is_fully_distributed
            and self.request_status == RequestStatus.ACCEPTED
        )

    def days_since_request(self) -> int:
        """Calculate how many days since the request was created."""
        from datetime import datetime

        delta = datetime.now() - self.created_at
        return delta.days

    def __repr__(self) -> str:
        return f"<BloodRequest(id={self.id}, requester_id={self.requester_id}, status={self.request_status}, group_id={self.request_group_id})>"

    # --- Table Configuration for Performance ---
    __table_args__ = (
        # Composite indexes for common hospital blood request queries
        Index("idx_request_facility_status", "facility_id", "request_status"),
        Index("idx_request_source_status", "source_facility_id", "request_status"),
        Index("idx_request_blood_urgent", "blood_type", "priority", "request_status"),
        Index("idx_request_created_status", "created_at", "request_status"),
        Index("idx_request_group_master", "request_group_id", "is_master_request"),
        Index("idx_request_requester_date", "requester_id", "created_at"),
        Index("idx_request_product_facility", "blood_product", "facility_id"),
        Index("idx_request_processing_priority", "processing_status", "priority"),
    )


class DashboardDailySummary(Base):
    __tablename__ = "dashboard_daily_summary"

    # --- Columns ---
    date: Mapped[Date] = mapped_column(Date, primary_key=True)
    total_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_transferred: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # --- Relationships ---
    facility_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="CASCADE"),
        primary_key=True,
    )
