import uuid
from sqlalchemy import Column, String, ForeignKey, DateTime, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base




class Facility(Base):

    __tablename__ = "facilities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, index=True)
    facility_name = Column(String(100), nullable=False)

    facility_manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    # facility_manager = relationship("User", back_populates="facility", uselist=False)
    facility_manager = relationship(
        "User",
        back_populates="facility",
        foreign_keys=[facility_manager_id],
        uselist=False
    )

    # Staff/lab_manager link (one-to-many)
    users = relationship(
        "User",
        back_populates="work_facility",
        foreign_keys="[User.facility_id]"
    )

    blood_bank = relationship("BloodBank", back_populates="facility", uselist=False)

    facility_email = Column(String(100), unique=True, index=True, nullable=False)
    facility_digital_address = Column(String(15), nullable=False)
    facility_contact_number = Column(String(20), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


    def __str__(self):
        return f"{self.facility_name} ({self.facility_email})"
