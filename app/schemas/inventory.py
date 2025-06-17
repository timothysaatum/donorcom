# from pydantic import BaseModel, Field, UUID4
# from typing import Optional
# from datetime import date, datetime


# class BloodInventoryBase(BaseModel):
#     blood_product: str = Field(..., description="Type of blood product (e.g., Whole Blood, Plasma)")
#     blood_type: str = Field(..., description="Blood type (e.g., A+, B-, O+)")
#     quantity: int = Field(..., ge=0, description="Units of blood available")
#     expiry_date: date = Field(..., description="Expiration date of the blood unit")


# class BloodInventoryCreate(BloodInventoryBase):
#     pass


# class BloodInventoryUpdate(BaseModel):
#     blood_product: Optional[str] = None
#     blood_type: Optional[str] = None
#     quantity: Optional[int] = Field(None, ge=0)
#     expiry_date: Optional[date] = None


# class BloodInventoryResponse(BloodInventoryBase):
#     id: UUID4
#     blood_bank_id: UUID4
#     added_by_id: Optional[UUID4]
#     created_at: datetime
#     updated_at: datetime

#     class Config:
#         from_attributes = True


# class BloodInventoryDetailResponse(BloodInventoryResponse):
#     # Optional: Include nested data about blood bank and user who added
#     blood_bank_name: Optional[str] = None
#     added_by_name: Optional[str] = None

#     class Config:
#         from_attributes = True
from pydantic import BaseModel, Field, field_validator, ConfigDict, FieldValidationInfo
from uuid import UUID
from datetime import datetime, date
from typing import Optional, List, Generic, TypeVar, Any, Dict
from enum import Enum


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class BloodInventoryCreate(BaseModel):
    blood_product: str = Field(..., min_length=1, max_length=50, description="Blood product type")
    blood_type: str = Field(..., min_length=1, max_length=10, description="Blood type (e.g., A+, B-, O+)")
    quantity: int = Field(..., gt=0, description="Quantity in units")
    expiry_date: date = Field(..., description="Expiration date")

    @field_validator('blood_type')
    def validate_blood_type(cls, v):
        valid_types = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
        if v not in valid_types:
            raise ValueError(f'Blood type must be one of: {", ".join(valid_types)}')
        return v

    @field_validator('blood_product')
    def validate_blood_product(cls, v):
        valid_products = ['Whole Blood', 'Red Blood Cells', 'Plasma', 'Platelets', 'Cryoprecipitate']
        if v not in valid_products:
            raise ValueError(f'Blood product must be one of: {", ".join(valid_products)}')
        return v

    @field_validator('expiry_date')
    def validate_expiry_date(cls, v):
        if v <= date.today():
            raise ValueError('Expiry date must be in the future')
        return v


class BloodInventoryUpdate(BaseModel):
    blood_product: Optional[str] = Field(None, min_length=1, max_length=50)
    blood_type: Optional[str] = Field(None, min_length=1, max_length=10)
    quantity: Optional[int] = Field(None, gt=0)
    expiry_date: Optional[date] = None

    @field_validator('blood_type')
    def validate_blood_type(cls, v):
        if v is not None:
            valid_types = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
            if v not in valid_types:
                raise ValueError(f'Blood type must be one of: {", ".join(valid_types)}')
        return v

    @field_validator('blood_product')
    def validate_blood_product(cls, v):
        if v is not None:
            valid_products = ['Whole Blood', 'Red Blood Cells', 'Plasma', 'Platelets', 'Cryoprecipitate']
            if v not in valid_products:
                raise ValueError(f'Blood product must be one of: {", ".join(valid_products)}')
        return v

    @field_validator('expiry_date')
    def validate_expiry_date(cls, v):
        if v is not None and v <= date.today():
            raise ValueError('Expiry date must be in the future')
        return v


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

    # class Config:
    #     from_attributes = True
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


# class BloodInventorySearchParams(BaseModel):

#     """Advanced search parameters for blood inventory"""
#     blood_types: Optional[List[str]] = Field(None, description="Filter by multiple blood types")
#     blood_products: Optional[List[str]] = Field(None, description="Filter by multiple blood products")
#     min_quantity: Optional[int] = Field(None, ge=0, description="Minimum quantity filter")
#     max_quantity: Optional[int] = Field(None, ge=0, description="Maximum quantity filter")
#     expiry_date_from: Optional[date] = Field(None, description="Filter by expiry date from")
#     expiry_date_to: Optional[date] = Field(None, description="Filter by expiry date to")
#     created_from: Optional[datetime] = Field(None, description="Filter by creation date from")
#     created_to: Optional[datetime] = Field(None, description="Filter by creation date to")
#     blood_bank_ids: Optional[List[UUID]] = Field(None, description="Filter by multiple blood banks")
#     search_term: Optional[str] = Field(None, min_length=1, max_length=100, description="General search term")

#     @field_validator('blood_types')
#     def validate_blood_types(cls, v):
#         if v is not None:
#             valid_types = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
#             for blood_type in v:
#                 if blood_type not in valid_types:
#                     raise ValueError(f'Invalid blood type: {blood_type}')
#         return v

#     @field_validator('blood_products')
#     def validate_blood_products(cls, v):
#         if v is not None:
#             valid_products = ['Whole Blood', 'Red Blood Cells', 'Plasma', 'Platelets', 'Cryoprecipitate']
#             for product in v:
#                 if product not in valid_products:
#                     raise ValueError(f'Invalid blood product: {product}')
#         return v

#     @field_validator('max_quantity')
#     def validate_quantity_range(cls, v, values):
#         if v is not None and 'min_quantity' in values and values['min_quantity'] is not None:
#             if v < values['min_quantity']:
#                 raise ValueError('max_quantity must be greater than or equal to min_quantity')
#         return v

#     @field_validator('expiry_date_to')
#     def validate_expiry_date_range(cls, v, values):
#         if v is not None and 'expiry_date_from' in values and values['expiry_date_from'] is not None:
#             if v < values['expiry_date_from']:
#                 raise ValueError('expiry_date_to must be greater than or equal to expiry_date_from')
#         return v

#     @field_validator('created_to')
#     def validate_created_date_range(cls, v, values):
#         if v is not None and 'created_from' in values and values['created_from'] is not None:
#             if v < values['created_from']:
#                 raise ValueError('created_to must be greater than or equal to created_from')
#         return v
class BloodInventorySearchParams(BaseModel):
    """Advanced search parameters for blood inventory"""
    blood_types: Optional[List[str]] = Field(None, description="Filter by multiple blood types")
    blood_products: Optional[List[str]] = Field(None, description="Filter by multiple blood products")
    min_quantity: Optional[int] = Field(None, ge=0, description="Minimum quantity filter")
    max_quantity: Optional[int] = Field(None, ge=0, description="Maximum quantity filter")
    expiry_date_from: Optional[date] = Field(None, description="Filter by expiry date from")
    expiry_date_to: Optional[date] = Field(None, description="Filter by expiry date to")
    created_from: Optional[datetime] = Field(None, description="Filter by creation date from")
    created_to: Optional[datetime] = Field(None, description="Filter by creation date to")
    blood_bank_ids: Optional[List[UUID]] = Field(None, description="Filter by multiple blood banks")
    search_term: Optional[str] = Field(None, min_length=1, max_length=100, description="General search term")

    @field_validator('blood_types')
    def validate_blood_types(cls, v):
        if v is not None:
            valid_types = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
            for blood_type in v:
                if blood_type not in valid_types:
                    raise ValueError(f'Invalid blood type: {blood_type}')
        return v

    @field_validator('blood_products')
    def validate_blood_products(cls, v):
        if v is not None:
            valid_products = ['Whole Blood', 'Red Blood Cells', 'Plasma', 'Platelets', 'Cryoprecipitate']
            for product in v:
                if product not in valid_products:
                    raise ValueError(f'Invalid blood product: {product}')
        return v

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