import uuid
from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class BloodBank(Base):
    __tablename__ = "blood_banks"

    # --- Columns ---
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    blood_bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # --- Relationships ---
    facility_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="CASCADE"),
        nullable=False,
    )
    manager_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=True,
        index=True,
    )

    facility = relationship("Facility", back_populates="blood_bank", uselist=False)
    manager_user = relationship("User", back_populates="blood_bank", uselist=False)
    blood_inventory = relationship(
        "BloodInventory", 
        back_populates="blood_bank", 
        cascade="all, delete-orphan",
    )
    outgoing_distributions = relationship(
        "BloodDistribution",
        back_populates="dispatched_from",
        foreign_keys="BloodDistribution.dispatched_from_id",
        cascade="all, delete-orphan",
    )

    # --- Methods ---
    def __str__(self) -> str:
        return f"{self.blood_bank_name} ({self.id})"