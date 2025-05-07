import uuid
from sqlalchemy import String, Column, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base



class BloodBank(Base):
    
    __tablename__ = "blood_banks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, index=True)
    phone = Column(String(15), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    blood_bank_name = Column(String(100), nullable=False)

    facility_id = Column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False)
    manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)

    facility = relationship("Facility", back_populates="blood_bank", uselist=False)
    manager_user = relationship("User", back_populates="blood_bank", uselist=False)
    blood_inventory = relationship("BloodInventory", back_populates="blood_bank", cascade="all, delete-orphan")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __str__(self):
        return f"{self.blood_bank_name} ({self.id})"
