import uuid
from typing import Optional
from sqlalchemy import String, DateTime, Integer, Date, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class BloodInventory(Base):
    __tablename__ = "blood_inventory"

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
    expiry_date: Mapped[Date] = mapped_column(Date, nullable=False)

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # --- Relationships ---
    blood_bank_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("blood_banks.id", ondelete="CASCADE"),
        nullable=False,
    )
    added_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    blood_bank = relationship("BloodBank", back_populates="blood_inventory")
    added_by = relationship("User", back_populates="added_blood_units")
    distributions = relationship(
        "BloodDistribution",
        back_populates="inventory_item",
        foreign_keys="BloodDistribution.blood_product_id",
    )

    # --- Methods ---
    def __str__(self) -> str:
        return f"{self.blood_product} ({self.blood_type})"