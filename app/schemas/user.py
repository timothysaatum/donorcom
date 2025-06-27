from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict, ValidationInfo, computed_field
from typing import Optional
from uuid import UUID
from enum import Enum
from datetime import datetime
from app.schemas.facility_schema import FacilityWithBloodBank




class UserBase(BaseModel):
    
    email: EmailStr
    first_name: str = Field(..., min_length = 3, max_length = 50)
    last_name: str = Field(..., min_length = 3, max_length = 50)
    phone: Optional[str] = Field(..., min_length = 10, max_length = 14)


class UserCreate(UserBase):
    
    password: str = Field(..., min_length = 8, max_length = 100)
    password_confirm: str
    role: str = Field("staff", pattern = "^(facility_administrator|lab_manager|staff)$")
    
    @field_validator('password_confirm')
    def passwords_match(cls, v:str, values:ValidationInfo) -> str:
        if 'password' in values.data and v != values.data['password']:
            raise ValueError('passwords do not match')
        return v
        
    @field_validator('password')
    def password_complexity(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('password must be at least 8 characters')
        
        if not any(c.isupper() for c in v):
            raise ValueError('password must contain at least one uppercase letter')
        
        if not any(c.isdigit() for c in v):
            raise ValueError('password must contain at least one digit')
        return v


class UserUpdate(BaseModel):

    email: Optional[EmailStr] = None
    first_name: str = Field(None, min_length = 3, max_length = 50)
    last_name: str = Field(None, min_length = 3, max_length = 50)
    phone: Optional[str] = Field(None, min_length = 10, max_length = 14)
    role: Optional[str] = Field(None, pattern = "^(facility_administrator|lab_manager|staff)$")


class UserResponse(UserBase):
    id: UUID
    role: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    model_config = ConfigDict(from_attributes = True)


# class UserWithFacility(UserResponse):
#     facility: Optional[FacilityWithBloodBank] = None
class UserRole(str, Enum):
    facility_administrator = "facility_administrator"
    lab_manager = "lab_manager"
    staff = "staff"

class BloodBankResponse(BaseModel):
    id: UUID
    phone: str
    email: str
    blood_bank_name: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class FacilityResponse(BaseModel):
    id: UUID
    facility_name: str
    facility_email: str
    facility_contact_number: Optional[str] = None
    facility_digital_address: str
    created_at: datetime
    blood_bank: Optional[BloodBankResponse] = None

    class Config:
        from_attributes = True

# class UserWithFacility(BaseModel):
#     id: UUID
#     first_name: str
#     last_name: str
#     email: str
#     role: UserRole
#     phone: Optional[str] = None
#     is_active: bool
#     created_at: datetime
#     last_login: Optional[datetime] = None
    
#     # For facility administrators
#     facility: Optional[FacilityResponse] = None
#     # For staff and lab managers
#     work_facility: Optional[FacilityResponse] = None

#     @computed_field
#     @property
#     def current_facility(self) -> Optional[FacilityResponse]:
#         """Return the facility associated with this user, regardless of their role"""
#         # For facility administrators, return the facility they manage
#         if self.facility:
#             return self.facility
#         # For staff/lab managers, return the facility they work at
#         elif self.work_facility:
#             return self.work_facility
#         return None

#     class Config:
#         from_attributes = True

#     def model_dump(self, **kwargs):
#         """Override model_dump to include current_facility in the response"""
#         data = super().model_dump(**kwargs)
        
#         # Replace facility field with current_facility for consistent API response
#         current_facility = self.current_facility
#         if current_facility:
#             data['facility'] = current_facility.model_dump() if hasattr(current_facility, 'model_dump') else current_facility
        
#         # Remove work_facility from the response to keep it clean
#         data.pop('work_facility', None)
        
#         return data
class UserWithFacility(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    email: str
    role: UserRole
    phone: Optional[str] = None
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None
    
    # For facility administrators - the facility they manage
    facility: Optional[FacilityResponse] = None
    # For staff and lab managers - the facility they work at
    work_facility: Optional[FacilityResponse] = None

    def model_dump(self, **kwargs):
        """Override model_dump to create a clean response structure"""
        data = super().model_dump(**kwargs)
        
        # For facility administrators, use 'facility'
        # For staff/lab managers, move work_facility to facility field
        if self.role == UserRole.facility_administrator:
            if self.facility:
                data['facility'] = self.facility.model_dump()
        else:
            if self.work_facility:
                data['facility'] = self.work_facility.model_dump()
        
        # Remove work_facility from response to avoid duplication
        data.pop('work_facility', None)
        
        return data


class AuthResponse(BaseModel):
    access_token: str
    user: UserWithFacility


class LoginSchema(BaseModel):
    email: str
    password: str
    
    
# class StaffResponse(UserResponse):
	
# 	class Config:
# 		orm_mode = True
