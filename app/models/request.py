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
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from app.db.base import Base
from app.schemas.distribution import DistributionStatus
import enum


class ProcessingStatus(str, enum.Enum):
    pending = "pending"
    initiated = "initiated"
    dispatched = "dispatched"
    completed = "completed"


class RequestStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    cancelled = "cancelled"


class PriorityStatus(str, enum.Enum):
    urgent = "urgent"
    not_urgent = "not urgent"


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
    is_master_request: Mapped[bool] = mapped_column(Boolean, default=False)

    blood_type: Mapped[str] = mapped_column(String(10), nullable=False)
    blood_product: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    request_status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus),
        default=RequestStatus.pending,
    )
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus),
        default=ProcessingStatus.pending,
    )
    priority: Mapped[Optional[PriorityStatus]] = mapped_column(
        Enum(PriorityStatus),
        nullable=True,
        default=PriorityStatus.not_urgent,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    option: Mapped[str] = mapped_column(String(10), default="sent")

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # --- Relationships ---
    requester_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    fulfilled_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
            if value in [RequestStatus.cancelled, RequestStatus.rejected]:
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
            if dist.status != DistributionStatus.cancelled
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
            DistributionStatus.pending_receive,
            DistributionStatus.in_transit,
            DistributionStatus.delivered,
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
            if dist.status == DistributionStatus.delivered
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
            self.priority == PriorityStatus.urgent
            and not self.is_fully_distributed
            and self.request_status == RequestStatus.accepted
        )

    def days_since_request(self) -> int:
        """Calculate how many days since the request was created."""
        from datetime import datetime

        delta = datetime.now() - self.created_at
        return delta.days

    def __repr__(self) -> str:
        return f"<BloodRequest(id={self.id}, requester_id={self.requester_id}, status={self.request_status}, group_id={self.request_group_id})>"


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
