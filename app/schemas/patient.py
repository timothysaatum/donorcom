from pydantic import BaseModel, Field, ConfigDict, StringConstraints
from uuid import UUID
from datetime import datetime
from typing import Optional, Annotated
import re


# --- Base Configuration for Performance ---
class BaseSchema(BaseModel):
    """Base schema with optimized configuration for performance"""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
        frozen=False,
        extra="forbid",
        from_attributes=True,
    )


class PatientCreate(BaseSchema):
    name: Annotated[
        str, StringConstraints(min_length=2, max_length=100, strip_whitespace=True)
    ] = Field(..., description="Patient full name")
    age: int = Field(..., gt=0, le=120, description="Patient age in years")
    sex: Annotated[str, StringConstraints(pattern=r"^(Male|Female|Other)$")] = Field(
        ..., description="Patient gender"
    )
    diagnosis: Optional[
        Annotated[str, StringConstraints(max_length=500, strip_whitespace=True)]
    ] = Field(None, description="Medical diagnosis")


class PatientResponse(PatientCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime


class PatientUpdate(BaseSchema):
    name: Optional[
        Annotated[
            str, StringConstraints(min_length=2, max_length=100, strip_whitespace=True)
        ]
    ] = None
    age: Optional[int] = Field(None, gt=0, le=120)
    sex: Optional[
        Annotated[str, StringConstraints(pattern=r"^(Male|Female|Other)$")]
    ] = None
    diagnosis: Optional[
        Annotated[str, StringConstraints(max_length=500, strip_whitespace=True)]
    ] = None
