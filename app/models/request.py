import uuid
from typing import Optional
from sqlalchemy import (
    Date, String, Integer, DateTime, ForeignKey, Enum, func, Text, Boolean
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
import enum


class ProcessingStatus(str, enum.Enum):
    pending = "pending"
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
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    option: Mapped[str] = mapped_column(String(10), default="sent")

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

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
    facility_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="CASCADE"),
    )

    requester = relationship("User", foreign_keys=[requester_id])
    fulfilled_by = relationship("User", foreign_keys=[fulfilled_by_id])
    facility = relationship("Facility", back_populates="blood_requests")
    track_states = relationship(
        "TrackState", 
        back_populates="blood_request", 
        cascade="all, delete-orphan",
    )

    # --- Methods ---
    def __repr__(self) -> str:
        return f"<BloodRequest(id={self.id}, requester_id={self.requester_id}, status={self.request_status}, group_id={self.request_group_id})>"


class DashboardDailySummary(Base):
    __tablename__ = "dashboard_daily_summary"

    # --- Columns ---
    date: Mapped[Date] = mapped_column(Date, primary_key=True)
    total_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_transferred: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # --- Relationships ---
    facility_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="CASCADE"),
        primary_key=True,
    )