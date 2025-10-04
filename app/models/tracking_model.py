import uuid
from typing import Optional
from sqlalchemy import String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from enum import Enum as PyEnum
from datetime import datetime, timezone


class TrackStateStatus(PyEnum):
    DISPATCHED = "dispatched"
    RECEIVED = "received"
    RETURNED = "returned"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    PENDING_RECEIVE = "pending receive"


class TrackState(Base):
    __tablename__ = "track_states"

    # --- Columns ---
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
    )
    # --- Relationships ---
    blood_distribution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("blood_distributions.id", ondelete="CASCADE"),
        nullable=True,
    )
    blood_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("blood_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    blood_distribution = relationship("BloodDistribution", back_populates="track_states")
    blood_request = relationship("BloodRequest", back_populates="track_states")
    created_by = relationship("User", foreign_keys=[created_by_id])

    # --- Methods ---
    def __str__(self) -> str:
        return f"TrackState({self.status}, {self.timestamp})"