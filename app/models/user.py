from sqlalchemy import Column, Integer, String, Enum, DateTime, Boolean
from app.db.base import Base
from sqlalchemy.sql import func
# from datetime import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)
    role = Column(Enum('facility_administrator', 'lab_manager', 'staff', name='user_roles'), nullable=False)
    phone_number = Column(String(20))
    status = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime, nullable=True)
    
    def update_login_time(self):
        """Call this method when user logs in"""
        self.last_login = func.now()

