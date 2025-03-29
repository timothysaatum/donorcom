from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
from typing import Optional
from datetime import datetime



class UserBase(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=5, max_length=50)
    phone: Optional[str] = Field(..., min_length=10, max_length=14)



class UserCreationBase(UserBase):
    password: str = Field(..., min_length=8, max_length=100)
    password_comnfirm: str

    role: str = Field("staff", pattern="^(facility_administrator|lab_manager|staff)$")

    @field_validator('password_comnfirm')
    def passwords_match(cls, v:str, values:dict) -> str:
        if 'password' in values and v != values.data['password']:
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
    

class UserResponse(UserBase):
    id: int
    role: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    # model_config = ConfigDict(from_attributes=True)