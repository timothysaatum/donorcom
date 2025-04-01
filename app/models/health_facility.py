import uuid
from sqlalchemy import Column, String, ForeignKey, DateTime, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class Facility(Base):
    __tablename__ = "facilities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, index=True)
    facility_name = Column(String(100), nullable=False)
    facility_email = Column(String(100), unique=True, index=True, nullable=False)
    facility_digital_address = Column(String(15), nullable=False)
    facility_contact_number = Column(String(20), nullable=True)

    # One-to-One Foreign Key
    facility_manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime, nullable=True)

    # Relationship
    facility_manager = relationship("User", back_populates="facility", uselist=False)

    def update_login_time(self):
        """Call this method when user logs in"""
        self.last_login = func.now()