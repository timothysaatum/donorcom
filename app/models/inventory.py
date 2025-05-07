import uuid
from sqlalchemy import String, Column, ForeignKey, DateTime, Integer, Date, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base


class BloodInventory(Base):
    __tablename__ = "blood_inventory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, index=True)
    blood_product = Column(String(50), nullable=False)  # e.g., "Whole Blood", "Plasma", "Platelets"
    blood_type = Column(String(10), nullable=False)     # e.g., "A+", "B-", "O+", "AB-"
    quantity = Column(Integer, nullable=False)          # Units of blood
    expiry_date = Column(Date, nullable=False)          # Expiration date
    
    blood_bank_id = Column(UUID(as_uuid=True), ForeignKey("blood_banks.id", ondelete="CASCADE"), nullable=False)
    added_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Relationships
    blood_bank = relationship("BloodBank", back_populates="blood_inventory")
    added_by = relationship("User", back_populates="added_blood_units")
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())