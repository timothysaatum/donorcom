from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    field_validator,
    ConfigDict,
    ValidationInfo,
    StringConstraints,
)
from typing import Optional, Annotated
from uuid import UUID
from datetime import datetime
from enum import Enum
import re


# --- Base Configuration for Performance ---
class BaseSchema(BaseModel):
    """Base schema"""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
        frozen=False,
        extra="forbid",
        from_attributes=True,
    )


class UserBase(BaseSchema):
    email: EmailStr
    first_name: Annotated[
        str, StringConstraints(min_length=2, max_length=50, strip_whitespace=True)
    ]
    last_name: Annotated[
        str, StringConstraints(min_length=2, max_length=50, strip_whitespace=True)
    ]
    phone: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_ghana_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v.strip() == "":
            return v
        v = v.strip()
        # Remove all non-digit characters except leading '+'
        if v.startswith("+"):
            cleaned = "+" + re.sub(r"[^\d]", "", v[1:])
        else:
            cleaned = re.sub(r"[^\d]", "", v)
        # Ghana mobile numbers: +233 followed by 9 digits (first digit 2-5), or 0 followed by 9 digits (first digit 2-5)
        # Examples: +233594438287, 0594438287
        if re.fullmatch(r"\+233[2-5]\d{8}", cleaned) or re.fullmatch(
            r"0[2-5]\d{8}", cleaned
        ):
            return cleaned
        raise ValueError(
            "Phone number must be a valid Ghana mobile number (e.g. +233594438287 or 0594438287)"
        )


class UserRole(str, Enum):
    facility_administrator = "facility_administrator"
    lab_manager = "lab_manager"
    staff = "staff"


class UserCreate(UserBase):
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)]
    password_confirm: str
    role: UserRole = Field(default=UserRole.staff, description="Hospital staff role")

    @field_validator("password_confirm")
    @classmethod
    def passwords_match(cls, v: str, values: ValidationInfo) -> str:
        if "password" in values.data and v != values.data["password"]:
            raise ValueError("passwords do not match")
        return v

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")

        # Enhanced security requirements for hospital system
        requirements = {
            "uppercase": bool(re.search(r"[A-Z]", v)),
            "lowercase": bool(re.search(r"[a-z]", v)),
            "digit": bool(re.search(r"\d", v)),
            "special": bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', v)),
        }

        missing = [req for req, met in requirements.items() if not met]
        if len(missing) > 1:
            raise ValueError(f'Password must contain: {", ".join(missing)}')

        return v


class UserUpdate(BaseSchema):
    email: Optional[EmailStr] = None
    first_name: Optional[
        Annotated[str, StringConstraints(min_length=2, max_length=50)]
    ] = None
    last_name: Optional[
        Annotated[str, StringConstraints(min_length=2, max_length=50)]
    ] = None
    phone: Optional[
        Annotated[
            str,
            StringConstraints(
                min_length=10, max_length=15, pattern=r"^\+?[\d\s\-\(\)]{10,15}$"
            ),
        ]
    ] = None
    role: Optional[UserRole] = Field(None, description="Hospital admin role")


class UserResponse(UserBase):
    id: UUID
    role: Optional[UserRole] = None
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    @classmethod
    def from_db_user(cls, user_model):
        """Create UserResponse from user model - optimized for hospital staff"""
        # Get the first (and only) role name
        role_name = user_model.roles[0].name if user_model.roles else "staff"

        return cls(
            id=user_model.id,
            email=user_model.email,
            first_name=user_model.first_name,
            last_name=user_model.last_name,
            phone=user_model.phone,
            role=UserRole(role_name),
            is_active=user_model.is_active,
            created_at=user_model.created_at,
            last_login=user_model.last_login,
        )


class BloodBankResponse(BaseSchema):
    id: UUID
    phone: str
    email: str
    blood_bank_name: str
    created_at: datetime
    updated_at: datetime


class FacilityResponse(BaseSchema):
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
            work_facility=user_model.work_facility,
        )

    def model_dump(self, **kwargs):
        """Override model_dump to create a clean response structure"""
        data = super().model_dump(**kwargs)

        # For facility administrators, use the facility they manage
        if self.role == UserRole.facility_administrator and self.facility:
            data["facility"] = self.facility
        # For staff/lab managers, use the facility they work at
        elif self.role in [UserRole.staff, UserRole.lab_manager] and self.work_facility:
            data["facility"] = self.work_facility
        else:
            # If no facility is found, set to None
            data["facility"] = None

        # Remove work_facility from response to avoid confusion
        data.pop("work_facility", None)

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
    user_id: UUID
    role: UserRole
