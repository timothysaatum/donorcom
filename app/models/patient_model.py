import uuid
from sqlalchemy import Column, String, Integer, DateTime, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(100), nullable=False, index=True)
    age = Column(Integer, nullable=False, index=True)
    sex = Column(String(10), nullable=False, index=True)
    diagnosis = Column(String(255), nullable=True, index=True)

    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # blood_requests = relationship("BloodRequest", back_populates="patient")

    # --- Table Configuration for Performance ---
    __table_args__ = (
        # Composite indexes for patient queries
        Index("idx_patient_name_age", "name", "age"),
        Index("idx_patient_sex_age", "sex", "age"),
        Index("idx_patient_created_name", "created_at", "name"),
    )
