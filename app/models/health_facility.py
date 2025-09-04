import uuid
from typing import Optional
from sqlalchemy import String, DateTime, Float, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Facility(Base):
    __tablename__ = "facilities"

    # --- Columns ---
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    facility_name: Mapped[str] = mapped_column(String(100), nullable=False)
    facility_email: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    facility_digital_address: Mapped[str] = mapped_column(String(15), nullable=False)
    facility_contact_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # --- Relationships ---
    facility_manager_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=True,
        index=True,
    )
    facility_manager = relationship(
        "User",
        back_populates="facility",
        foreign_keys=[facility_manager_id],
        uselist=False,
    )

    users = relationship(
        "User",
        back_populates="work_facility",
        foreign_keys="User.work_facility_id",
        cascade="all, delete-orphan",
    )

    blood_bank = relationship(
        "BloodBank", 
        back_populates="facility", 
        uselist=False,
        cascade="all, delete-orphan",
    )

    blood_requests = relationship(
        "BloodRequest",
        back_populates="facility",
        cascade="all, delete-orphan",
    )

    incoming_distributions = relationship(
        "BloodDistribution",
        back_populates="dispatched_to",
        foreign_keys="BloodDistribution.dispatched_to_id",
        cascade="all, delete-orphan",
    )

    dashboard_summaries = relationship(
        "DashboardDailySummary",
        cascade="all, delete-orphan",
    )

    # --- Methods ---
    def __str__(self) -> str:
        return f"{self.facility_name} ({self.facility_email})"