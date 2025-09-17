import uuid
from typing import Optional
from sqlalchemy import String, ForeignKey, DateTime, Enum, Integer, func, Date
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from app.db.base import Base
from app.schemas.distribution import DistributionStatus


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
    status: Mapped[DistributionStatus] = mapped_column(
        Enum(DistributionStatus, name="distribution_status"),
        nullable=False,
        default=DistributionStatus.pending_receive,
    )

    date_dispatched: Mapped[Optional[DateTime]] = mapped_column(DateTime, nullable=True)
    date_delivered: Mapped[Optional[DateTime]] = mapped_column(DateTime, nullable=True)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Additional tracking fields for blood products
    batch_number: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Batch number for inventory tracking and traceability",
    )
    expiry_date: Mapped[Optional[Date]] = mapped_column(
        Date, nullable=True, comment="Expiry date of the blood product"
    )
    temperature_maintained: Mapped[Optional[bool]] = mapped_column(
        nullable=True,
        default=True,
        comment="Whether proper temperature was maintained during transport",
    )

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # --- Relationships ---
    blood_product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("blood_inventory.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("blood_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,  # Add index for query performance
        comment="Link to the original blood request that triggered this distribution",
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

    inventory_item = relationship(
        "BloodInventory",
        foreign_keys=[blood_product_id],
        back_populates="distributions",
    )
    blood_request = relationship(
        "BloodRequest",
        foreign_keys=[request_id],
        back_populates="distributions",
    )
    dispatched_from = relationship(
        "BloodBank",
        foreign_keys=[dispatched_from_id],
        back_populates="outgoing_distributions",
    )
    dispatched_to = relationship(
        "Facility",
        foreign_keys=[dispatched_to_id],
        back_populates="incoming_distributions",
    )
    created_by = relationship("User", foreign_keys=[created_by_id])
    track_states = relationship(
        "TrackState",
        back_populates="blood_distribution",
        cascade="all, delete-orphan",
    )

    @validates("quantity")
    def validate_quantity(self, key, value):
        """Validate that quantity is positive."""
        if value <= 0:
            raise ValueError("Quantity must be greater than 0")
        return value

    @validates("expiry_date")
    def validate_expiry_date(self, key, value):
        """Validate that expiry date is not in the past."""
        if value is not None:
            from datetime import date

            if value < date.today():
                raise ValueError("Cannot distribute expired blood products")
        return value

    @validates("batch_number")
    def validate_batch_number(self, key, value):
        """Validate batch number format if provided."""
        if value is not None:
            if value.strip() == "":
                raise ValueError("Batch number cannot be empty string")
            if value.lower() == "string":
                raise ValueError("Batch number cannot be the literal word 'string'")
        return value.strip() if value else value

    @validates("tracking_number")
    def validate_tracking_number(self, key, value):
        """Validate tracking number format if provided."""
        if value is not None:
            if value.strip() == "":
                raise ValueError("Tracking number cannot be empty string")
            if value.lower() == "string":
                raise ValueError("Tracking number cannot be the literal word 'string'")
        return value.strip() if value else value

    @validates("date_delivered")
    def validate_date_delivered(self, key, value):
        """Validate that date_delivered is only set when status is delivered."""
        # Skip validation if value is None (clearing the field)
        if value is None:
            return value

        # Skip validation during initial object creation
        if not hasattr(self, "id") or self.id is None:
            return value

        # Skip validation if we're in the middle of an update operation
        # Check if this is being called during a bulk update
        if hasattr(self, "_sa_instance_state") and self._sa_instance_state.session:
            session = self._sa_instance_state.session
            # If the session has pending changes, we're likely in the middle of an update
            if session.dirty or session.new:
                return value

        # Only validate if status is not delivered
        if self.status != DistributionStatus.delivered:
            raise ValueError(
                "date_delivered can only be set when status is 'delivered'"
            )
        return value

    @validates("date_dispatched")
    def validate_date_dispatched(self, key, value):
        """Validate that date_dispatched is only set when status is in_transit or delivered."""
        # Skip validation if value is None (clearing the field)
        if value is None:
            return value

        # Skip validation during initial object creation
        if not hasattr(self, "id") or self.id is None:
            return value

        # Skip validation if we're in the middle of an update operation
        if hasattr(self, "_sa_instance_state") and self._sa_instance_state.session:
            session = self._sa_instance_state.session
            # If the session has pending changes, we're likely in the middle of an update
            if session.dirty or session.new:
                return value

        # Only validate if status doesn't allow dispatched date
        if self.status not in [
            DistributionStatus.in_transit,
            DistributionStatus.delivered,
        ]:
            raise ValueError(
                "date_dispatched can only be set when status is 'in_transit' or 'delivered'"
            )
        return value

    @validates("status")
    def validate_status_transition(self, key, value):
        """Validate status transitions and sync with related request if applicable."""
        # Define valid status transitions
        valid_transitions = {
            DistributionStatus.pending_receive: [
                DistributionStatus.pending_receive,  # Allow same status
                DistributionStatus.in_transit,
                DistributionStatus.cancelled,
            ],
            DistributionStatus.in_transit: [
                DistributionStatus.in_transit,  # Allow same status
                DistributionStatus.delivered,
                DistributionStatus.returned,
            ],
            DistributionStatus.delivered: [
                DistributionStatus.delivered,  # Allow same status
                DistributionStatus.returned,
            ],
            DistributionStatus.cancelled: [
                DistributionStatus.cancelled,  # Allow same status
            ],  # Terminal state
            DistributionStatus.returned: [
                DistributionStatus.returned,  # Allow same status
            ],  # Terminal state
        }

        # Allow initial status setting
        if self.status is None:
            return value

        # Check if transition is valid (including same status)
        if value not in valid_transitions.get(self.status, []):
            raise ValueError(f"Invalid status transition from {self.status} to {value}")

        return value

    def update_request_processing_status(self):
        """Update the related blood request's processing status based on distribution status."""
        if not self.blood_request:
            return

        # Import here to avoid circular imports
        from app.models.request import ProcessingStatus

        # Professional tracking status mapping
        status_mapping = {
            DistributionStatus.pending_receive: ProcessingStatus.initiated,  # Distribution created -> initiated
            DistributionStatus.in_transit: ProcessingStatus.dispatched,  # In transit -> dispatched
            DistributionStatus.delivered: ProcessingStatus.completed,  # Delivered -> completed
            DistributionStatus.cancelled: ProcessingStatus.pending,  # Reset to pending for retry
            DistributionStatus.returned: ProcessingStatus.pending,  # Reset to pending for retry
        }

        new_processing_status = status_mapping.get(self.status)
        if (
            new_processing_status
            and self.blood_request.processing_status != new_processing_status
        ):
            old_status = self.blood_request.processing_status
            self.blood_request.processing_status = new_processing_status

            # Create audit trail for status change
            self._create_status_change_audit(old_status, new_processing_status)

    def is_product_safe_for_distribution(self) -> bool:
        """Check if the blood product is safe for distribution."""
        from datetime import date

        # Check expiry date
        if self.expiry_date and self.expiry_date <= date.today():
            return False

        # Check temperature maintenance (if tracked)
        if self.temperature_maintained is False:
            return False

        return True

    def get_days_until_expiry(self) -> Optional[int]:
        """Get number of days until the product expires."""
        if not self.expiry_date:
            return None

        from datetime import date

        delta = self.expiry_date - date.today()
        return delta.days

    def mark_temperature_breach(self):
        """Mark that temperature was not maintained during transport."""
        self.temperature_maintained = False
        # Consider auto-updating status to returned or cancelled
        if self.status in [DistributionStatus.in_transit]:
            # This would need to be handled by the service layer
            pass

    def _create_status_change_audit(self, old_status, new_status):
        """Create audit trail for processing status changes."""
        try:
            # Import here to avoid circular imports
            from app.models.tracking_model import TrackState
            from app.schemas.tracking_schema import TrackStateStatus
            from sqlalchemy.orm import Session

            # Get the current session from the object
            session = Session.object_session(self)
            if not session:
                return

            # Map processing status to track state status
            status_mapping = {
                "initiated": TrackStateStatus.requested,
                "dispatched": TrackStateStatus.dispatched,
                "completed": TrackStateStatus.delivered,
                "pending": TrackStateStatus.pending,
            }

            track_status = status_mapping.get(
                new_status.value, TrackStateStatus.processing
            )

            # Create tracking record
            track_state = TrackState(
                blood_request_id=self.blood_request.id,
                blood_distribution_id=self.id,
                status=track_status,
                location=(
                    self.dispatched_to.facility_name
                    if self.dispatched_to
                    else "Unknown Location"
                ),
                notes=f"Processing status updated from {old_status.value} to {new_status.value} due to distribution status change",
                created_by_id=self.created_by_id,
            )

            session.add(track_state)
        except Exception:
            # Silently handle audit failures to not disrupt main flow
            pass

    # --- Methods ---
    def __str__(self) -> str:
        request_info = f" (Request: {self.request_id})" if self.request_id else ""
        return f"{self.blood_product} ({self.blood_type}) → {self.dispatched_to.facility_name}{request_info}"
