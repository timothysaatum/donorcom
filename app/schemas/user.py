from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict, ValidationInfo
from typing import Optional
from uuid import UUID
from datetime import datetime
from app.schemas.facility_schema import FacilityWithBloodBank




class UserBase(BaseModel):
    
    email: EmailStr
    name: str = Field(..., min_length = 5, max_length = 50)
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
    name: str = Field(None, min_length = 5, max_length = 50)
    phone: Optional[str] = Field(None, min_length = 10, max_length = 14)
    role: Optional[str] = Field(None, pattern = "^(facility_administrator|lab_manager|staff)$")


class UserResponse(UserBase):
    id: UUID
    role: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    model_config = ConfigDict(from_attributes = True)


class UserWithFacility(UserResponse):
    facility: Optional[FacilityWithBloodBank] = None


class AuthResponse(BaseModel):
    access_token: str
    user: UserWithFacility


class LoginSchema(BaseModel):
    email: str
    password: str
    
    
# class StaffResponse(UserResponse):
	
# 	class Config:
# 		orm_mode = True