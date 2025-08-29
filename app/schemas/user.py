from pydantic import (
    BaseModel, 
    EmailStr, 
    Field, 
    field_validator, 
    ConfigDict, 
    ValidationInfo
)
from typing import Optional
from uuid import UUID
from datetime import datetime
from enum import Enum


class UserBase(BaseModel):
    email: EmailStr
    first_name: str = Field(..., min_length=3, max_length=50)
    last_name: str = Field(..., min_length=3, max_length=50)
    phone: Optional[str] = Field(None, min_length=10, max_length=14)


class UserRole(str, Enum):
    facility_administrator = "facility_administrator"
    lab_manager = "lab_manager"
    staff = "staff"


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=100)
    password_confirm: str
    role: UserRole = Field(default=UserRole.staff, description="User role")
    
    @field_validator('password_confirm')
    def passwords_match(cls, v: str, values: ValidationInfo) -> str:
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
    first_name: Optional[str] = Field(None, min_length=3, max_length=50)
    last_name: Optional[str] = Field(None, min_length=3, max_length=50)
    phone: Optional[str] = Field(None, min_length=10, max_length=14)
    role: Optional[UserRole] = Field(None, description="User role")


class UserResponse(UserBase):
    id: UUID
    role: Optional[UserRole] = None
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    @classmethod
    def from_db_user(cls, user_model):
        """Create UserResponse from SQLAlchemy user model"""
        # Get the first (and only) role name
        role_name = user_model.roles[0].name #if user_model.roles else None

        return cls(
            id=user_model.id,
            email=user_model.email,
            first_name=user_model.first_name,
            last_name=user_model.last_name,
            phone=user_model.phone,
            role=UserRole(role_name),
            is_active=user_model.is_active,
            created_at=user_model.created_at,
            last_login=user_model.last_login
        )


class BloodBankResponse(BaseModel):
    id: UUID
    phone: str
    email: str
    blood_bank_name: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FacilityResponse(BaseModel):
    id: UUID
    facility_name: str
    facility_email: str
    facility_contact_number: Optional[str] = None
    facility_digital_address: str
    created_at: datetime
    blood_bank: Optional[BloodBankResponse] = None

    model_config = ConfigDict(from_attributes=True)


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
    work_facility: Optional[FacilityResponse] = Field(None, exclude=True)

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    @classmethod
    def from_db_user(cls, user_model):
        """Create UserWithFacility from SQLAlchemy user model"""
        # Get the first (and only) role name
        role_name = user_model.roles[0].name if user_model.roles else "staff"
        
        return cls(
            id=user_model.id,
            first_name=user_model.first_name,
            last_name=user_model.last_name,
            email=user_model.email,
            role=UserRole(role_name),
            phone=user_model.phone,
            is_active=user_model.is_active,
            created_at=user_model.created_at,
            last_login=user_model.last_login,
            facility=user_model.facility,
            work_facility=user_model.work_facility
        )

    def model_dump(self, **kwargs):
        """Override model_dump to create a clean response structure"""
        data = super().model_dump(**kwargs)
        
        # For facility administrators, use the facility they manage
        if self.role == UserRole.facility_administrator and self.facility:
            data['facility'] = self.facility
        # For staff/lab managers, use the facility they work at
        elif self.role in [UserRole.staff, UserRole.lab_manager] and self.work_facility:
            data['facility'] = self.work_facility
        else:
            # If no facility is found, set to None
            data['facility'] = None
        
        # Remove work_facility from response to avoid confusion
        data.pop('work_facility', None)
        
        return data


class AuthResponse(BaseModel):
    access_token: str
    user: UserWithFacility


class LoginSchema(BaseModel):
    email: str
    password: str


# Utility schema for role assignment
class ChangeUserRoleRequest(BaseModel):
    """Schema for changing a user's role"""
    user_id: UUID
    role: UserRole