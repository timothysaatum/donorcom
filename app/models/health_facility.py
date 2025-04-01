from sqlalchemy import Column, Integer, String, Enum, DateTime, Boolean
from app.db.base import Base
from sqlalchemy.sql import func


class Facility(Base):
    __tablename__ = "facilities"

    id = Column(Integer, primary_key=True, index=True)
    facility_name = Column(String(100), nullable=False)
    facility_email = Column(String(100), unique=True, index=True, nullable=False)
    facility_digital_address = Column(String(15), nullable=False)
    facility_contact_number = Column(String(20))
    facility_managing_director = Column(ForeignKey(User))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def update_login_time(self):
        """Call this method when user logs in"""
        self.last_login = func.now()

