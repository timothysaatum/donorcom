from sqlalchemy import Column, String, Enum, DateTime, Boolean
from app.db.base import Base
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid





class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)
    role = Column(Enum('facility_administrator', 'lab_manager', 'staff', name='user_roles'), nullable=False)
    phone = Column(String(20))
    is_active = Column(Boolean, default=True)
    status = Column(Boolean, default=True)

    facility = relationship("Facility", back_populates="facility_manager", uselist=False)
    blood_bank = relationship("BloodBank", back_populates="manager_user", uselist=False)
    added_blood_units = relationship("BloodInventory", back_populates="added_by")
    is_verified = Column(Boolean, default=False)
    verification_token = Column(String, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime, nullable=True)

    
    def update_login_time(self):
        """Call this method when user logs in"""
        self.last_login = func.now()

