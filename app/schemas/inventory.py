from pydantic import BaseModel, Field, field_validator, ConfigDict, FieldValidationInfo
from uuid import UUID
from datetime import datetime, date
from typing import Optional, List, Generic, TypeVar, Any, Dict
from enum import Enum


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class BloodProduct(str, Enum):
    WHOLE_BLOOD = "Whole Blood"
    RED_BLOOD_CELLS = "Red Blood Cells"
    PACKED_RED_BLOOD_CELLS = "Packed Red Blood Cells"
    LEUKOCYTE_REDUCED_RED_CELLS = "Leukocyte Reduced Red Cells"
    WASHED_RED_BLOOD_CELLS = "Washed Red Blood Cells"
    IRRADIATED_BLOOD = "Irradiated Blood"
    PLASMA = "Plasma"
    FRESH_FROZEN_PLASMA = "Fresh Frozen Plasma"
    FROZEN_PLASMA = "Frozen Plasma"
    APHERESIS_PLASMA = "Apheresis Plasma"
    PLATELETS = "Platelets"
    PLATELET_CONCENTRATE = "Platelet Concentrate"
    APHERESIS_PLATELETS = "Apheresis Platelets"
    CRYOPRECIPITATE = "Cryoprecipitate"
    GRANULOCYTES = "Granulocytes"


class BloodType(str, Enum):
    A_POS = "A+"
    A_NEG = "A-"
    B_POS = "B+"
    B_NEG = "B-"
    AB_POS = "AB+"
    AB_NEG = "AB-"
    O_POS = "O+"
    O_NEG = "O-"


class BloodInventoryCreate(BaseModel):
    blood_product: Optional[BloodProduct] = Field(None, description="Type of blood product")
    blood_type: Optional[BloodType] = Field(None, description="Blood group")
    quantity: int = Field(..., gt=0, description="Quantity in units")
    expiry_date: date = Field(..., description="Expiration date of the blood unit")


class BloodInventoryUpdate(BaseModel):

    blood_product: Optional[BloodProduct] = Field(None, description="Type of blood product")
    blood_type: Optional[BloodType] = Field(None, description="Blood group")
    quantity: Optional[int] = Field(None, gt=0)
    expiry_date: date = Field(..., description="Expiration date of the blood unit")


class BloodInventoryBatchCreate(BaseModel):
    blood_units: List[BloodInventoryCreate] = Field(..., min_items=1, max_items=1000)
    
    @field_validator('blood_units')
    def validate_batch_size(cls, v):
        if len(v) > 1000:
            raise ValueError('Batch size cannot exceed 1000 units')
        return v


class BloodInventoryBatchUpdate(BaseModel):
    updates: List[Dict[str, Any]] = Field(..., min_items=1, max_items=1000)
    
    @field_validator('updates')
    def validate_updates(cls, v):
        for update in v:
            if 'id' not in update:
                raise ValueError('Each update must contain an ID field')
        return v


class BloodInventoryBatchDelete(BaseModel):
    unit_ids: List[UUID] = Field(..., min_items=1, max_items=1000)


class BloodInventoryResponse(BaseModel):

    id: UUID
    blood_product: str
    blood_type: str
    quantity: int
    expiry_date: date
    blood_bank_id: UUID
    added_by_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BloodInventoryDetailResponse(BloodInventoryResponse):

    blood_bank_name: Optional[str] = None
    added_by_name: Optional[str] = None


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page (max 100)")
    sort_by: Optional[str] = Field(default=None, description="Field to sort by")
    sort_order: SortOrder = Field(default=SortOrder.DESC, description="Sort order")

    @field_validator('sort_by')
    def validate_sort_by(cls, v):
        if v is not None:
            allowed_fields = [
                'created_at', 'updated_at', 'expiry_date', 
                'blood_type', 'blood_product', 'quantity'
            ]
            if v not in allowed_fields:
                raise ValueError(f'Sort field must be one of: {", ".join(allowed_fields)}')
        return v


T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):

    items: List[T]
    total_items: int
    total_pages: int
    current_page: int
    page_size: int
    has_next: bool
    has_prev: bool

    model_config = ConfigDict(arbitrary_types_allowed=True)


class BloodInventoryFilter(BaseModel):

    blood_bank_id: Optional[UUID] = None
    blood_type: Optional[str] = None
    blood_product: Optional[str] = None
    expiry_date_from: Optional[datetime] = None
    expiry_date_to: Optional[datetime] = None
    search_term: Optional[str] = Field(None, min_length=1, max_length=100)
    expiring_in_days: Optional[int] = Field(None, ge=1, le=365)


class BatchOperationResponse(BaseModel):
    
    success: bool
    processed_count: int
    failed_count: int = 0
    errors: List[str] = []
    created_ids: Optional[List[UUID]] = None


class InventoryStatistics(BaseModel):

    total_units: int
    total_quantity: int
    blood_type_distribution: List[Dict[str, Any]]
    product_distribution: List[Dict[str, Any]]
    expiring_soon: Dict[str, int]


class BloodInventorySearchParams(BaseModel):
    """Advanced search parameters for blood inventory"""
    blood_product: Optional[BloodProduct] = Field(None, description="Type of blood product")
    blood_type: Optional[BloodType] = Field(None, description="Blood group")
    min_quantity: Optional[int] = Field(None, ge=0, description="Minimum quantity filter")
    max_quantity: Optional[int] = Field(None, ge=0, description="Maximum quantity filter")
    expiry_date_from: Optional[date] = Field(None, description="Filter by expiry date from")
    expiry_date_to: Optional[date] = Field(None, description="Filter by expiry date to")
    created_from: Optional[datetime] = Field(None, description="Filter by creation date from")
    created_to: Optional[datetime] = Field(None, description="Filter by creation date to")
    blood_bank_ids: Optional[List[UUID]] = Field(None, description="Filter by multiple blood banks")
    search_term: Optional[str] = Field(None, min_length=1, max_length=100, description="General search term")


    @field_validator('max_quantity')
    def validate_quantity_range(cls, v, info: FieldValidationInfo):
        min_q = info.data.get('min_quantity')
        if v is not None and min_q is not None and v < min_q:
            raise ValueError('max_quantity must be greater than or equal to min_quantity')
        return v

    @field_validator('expiry_date_to')
    def validate_expiry_date_range(cls, v, info: FieldValidationInfo):
        date_from = info.data.get('expiry_date_from')
        if v is not None and date_from is not None and v < date_from:
            raise ValueError('expiry_date_to must be greater than or equal to expiry_date_from')
        return v

    @field_validator('created_to')
    def validate_created_date_range(cls, v, info: FieldValidationInfo):
        created_from = info.data.get('created_from')
        if v is not None and created_from is not None and v < created_from:
            raise ValueError('created_to must be greater than or equal to created_from')
        return v