from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class PatientCreate(BaseModel):
    name: str
    age: int = Field(..., gt=0, lt=150)
    sex: str = Field(..., pattern="^(Male|Female|Other)$")
    diagnosis: str | None = None


class PatientResponse(PatientCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PatientUpdate(BaseModel):
    name: str | None = None
    age: int | None = Field(None, gt=0, lt=150)
    sex: str | None = Field(None, pattern="^(Male|Female|Other)$")
    diagnosis: str | None = None