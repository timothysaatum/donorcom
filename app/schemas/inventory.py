from pydantic import BaseModel, Field, field_validator, ConfigDict, ValidationInfo
from uuid import UUID
from datetime import datetime, date
from typing import Optional, List, Generic, TypeVar, Any, Dict
from enum import Enum


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class BloodType(str, Enum):
    """Enum for valid blood types"""

    A_POSITIVE = "A+"
    A_NEGATIVE = "A-"
    B_POSITIVE = "B+"
    B_NEGATIVE = "B-"
    AB_POSITIVE = "AB+"
    AB_NEGATIVE = "AB-"
    O_POSITIVE = "O+"
    O_NEGATIVE = "O-"

    @classmethod
    def get_values(cls) -> List[str]:
        """Get all valid blood type values"""
        return [item.value for item in cls]


class BloodProduct(str, Enum):
    """Enum for valid blood products with standardized naming"""

    WHOLE_BLOOD = "Whole Blood"
    RED_BLOOD_CELLS = "Red Blood Cells"
    RED_CELLS = "Red Cells"  # Alternative name for Red Blood Cells
    PLASMA = "Plasma"
    PLATELETS = "Platelets"
    CRYOPRECIPITATE = "Cryoprecipitate"
    FRESH_FROZEN_PLASMA = "Fresh Frozen Plasma"
    ALBUMIN = "Albumin"

    @classmethod
    def get_values(cls) -> List[str]:
        """Get all valid blood product values"""
        return [item.value for item in cls]

    @classmethod
    def get_all_accepted_values(cls) -> List[str]:
        """Get all accepted values including case variations"""
        base_values = cls.get_values()
        case_variations = []

        # Add lowercase versions
        for value in base_values:
            case_variations.append(value.lower())

        # Add specific common variations
        variations = {
            "red blood cells": "Red Blood Cells",
            "red cells": "Red Cells",
            "platelets": "Platelets",
            "cryoprecipitate": "Cryoprecipitate",
            "fresh frozen plasma": "Fresh Frozen Plasma",
            "albumin": "Albumin",
            "whole blood": "Whole Blood",
        }

        return base_values + list(variations.keys())

    @classmethod
    def normalize_product_name(cls, product_name: str) -> str:
        """Normalize product name to standard enum value"""
        # Direct match first
        for product in cls:
            if product.value == product_name:
                return product.value

        # Case-insensitive match with normalization
        product_lower = product_name.lower()
        normalization_map = {
            "whole blood": cls.WHOLE_BLOOD.value,
            "red blood cells": cls.RED_BLOOD_CELLS.value,
            "red cells": cls.RED_CELLS.value,
            "plasma": cls.PLASMA.value,
            "platelets": cls.PLATELETS.value,
            "cryoprecipitate": cls.CRYOPRECIPITATE.value,
            "fresh frozen plasma": cls.FRESH_FROZEN_PLASMA.value,
            "albumin": cls.ALBUMIN.value,
        }

        return normalization_map.get(product_lower, product_name)


class BloodInventoryCreate(BaseModel):
    blood_product: str = Field(
        ..., min_length=1, max_length=50, description="Blood product type"
    )
    blood_type: str = Field(
        ..., min_length=1, max_length=10, description="Blood type (e.g., A+, B-, O+)"
    )
    quantity: int = Field(..., gt=0, description="Quantity in units")
    expiry_date: date = Field(..., description="Expiration date of the blood unit")

    @field_validator("blood_type")
    @classmethod
    def validate_blood_type(cls, v: str) -> str:
        if v not in BloodType.get_values():
            raise ValueError(
                f'Blood type must be one of: {", ".join(BloodType.get_values())}'
            )
        return v

    @field_validator("blood_product")
    @classmethod
    def validate_blood_product(cls, v: str) -> str:
        if v not in BloodProduct.get_all_accepted_values():
            raise ValueError(
                f'Blood product must be one of: {", ".join(BloodProduct.get_values())}'
            )
        # Normalize the product name
        return BloodProduct.normalize_product_name(v)

    @field_validator("expiry_date")
    @classmethod
    def validate_expiry_date(cls, v: date) -> date:
        if v < date.today():
            raise ValueError("Expiry date cannot be in the past")
        return v


class BloodInventoryUpdate(BaseModel):
    blood_product: Optional[str] = Field(None, min_length=1, max_length=50)
    blood_type: Optional[str] = Field(None, min_length=1, max_length=10)
    quantity: Optional[int] = Field(None, gt=0)
    expiry_date: Optional[date] = Field(
        None, description="Expiration date of the blood unit"
    )

    @field_validator("blood_type")
    @classmethod
    def validate_blood_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in BloodType.get_values():
            raise ValueError(
                f'Blood type must be one of: {", ".join(BloodType.get_values())}'
            )
        return v

    @field_validator("blood_product")
    @classmethod
    def validate_blood_product(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if v not in BloodProduct.get_all_accepted_values():
                raise ValueError(
                    f'Blood product must be one of: {", ".join(BloodProduct.get_values())}'
                )
            return BloodProduct.normalize_product_name(v)
        return v

    @field_validator("expiry_date")
    @classmethod
    def validate_expiry_date(cls, v: Optional[date]) -> Optional[date]:
        if v is not None and v < date.today():
            raise ValueError("Expiry date cannot be in the past")
        return v


class BloodInventoryBatchCreate(BaseModel):
    blood_units: List[BloodInventoryCreate] = Field(..., min_length=1, max_length=1000)

    @field_validator("blood_units")
    @classmethod
    def validate_batch_size(
        cls, v: List[BloodInventoryCreate]
    ) -> List[BloodInventoryCreate]:
        if len(v) > 1000:
            raise ValueError("Batch size cannot exceed 1000 units")
        return v


class BloodInventoryBatchUpdate(BaseModel):
    updates: List[Dict[str, Any]] = Field(..., min_length=1, max_length=1000)

    @field_validator("updates")
    @classmethod
    def validate_updates(cls, v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for i, update in enumerate(v):
            if "id" not in update:
                raise ValueError(f"Update at index {i} must contain an ID field")

            # Validate blood_type if present
            if (
                "blood_type" in update
                and update["blood_type"] not in BloodType.get_values()
            ):
                raise ValueError(
                    f'Invalid blood type in update {i}: {update["blood_type"]}'
                )

            # Validate blood_product if present
            if "blood_product" in update:
                if (
                    update["blood_product"]
                    not in BloodProduct.get_all_accepted_values()
                ):
                    raise ValueError(
                        f'Invalid blood product in update {i}: {update["blood_product"]}'
                    )
                # Normalize product name
                update["blood_product"] = BloodProduct.normalize_product_name(
                    update["blood_product"]
                )

            # Validate quantity if present
            if "quantity" in update and (
                not isinstance(update["quantity"], int) or update["quantity"] <= 0
            ):
                raise ValueError(
                    f"Invalid quantity in update {i}: must be a positive integer"
                )

        return v


class BloodInventoryBatchDelete(BaseModel):
    unit_ids: List[UUID] = Field(..., min_length=1, max_length=1000)

    @field_validator("unit_ids")
    @classmethod
    def validate_unit_ids(cls, v: List[UUID]) -> List[UUID]:
        if len(v) > 1000:
            raise ValueError("Cannot delete more than 1000 units in a single batch")
        # Remove duplicates while preserving order
        seen = set()
        unique_ids = []
        for unit_id in v:
            if unit_id not in seen:
                seen.add(unit_id)
                unique_ids.append(unit_id)
        return unique_ids


class BloodInventoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    blood_product: str
    blood_type: str
    quantity: int
    expiry_date: date
    blood_bank_id: UUID
    added_by_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    @field_validator("blood_type")
    @classmethod
    def validate_response_blood_type(cls, v: str) -> str:
        # Ensure response data is valid
        if v not in BloodType.get_values():
            raise ValueError(f"Invalid blood type in response: {v}")
        return v

    @field_validator("blood_product")
    @classmethod
    def validate_response_blood_product(cls, v: str) -> str:
        # Normalize product name for consistency in responses
        return BloodProduct.normalize_product_name(v)


class BloodInventoryDetailResponse(BloodInventoryResponse):
    blood_bank_name: Optional[str] = None
    added_by_name: Optional[str] = None


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    page_size: int = Field(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    )
    sort_by: Optional[str] = Field(default=None, description="Field to sort by")
    sort_order: SortOrder = Field(default=SortOrder.DESC, description="Sort order")

    @field_validator("sort_by")
    @classmethod
    def validate_sort_by(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            allowed_fields = [
                "created_at",
                "updated_at",
                "expiry_date",
                "blood_type",
                "blood_product",
                "quantity",
            ]
            if v not in allowed_fields:
                raise ValueError(
                    f'Sort field must be one of: {", ".join(allowed_fields)}'
                )
        return v


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: List[T]
    total_items: int
    total_pages: int
    current_page: int
    page_size: int
    has_next: bool
    has_prev: bool


class BloodInventoryFilter(BaseModel):
    blood_bank_id: Optional[UUID] = None
    blood_type: Optional[str] = None
    blood_product: Optional[str] = None
    expiry_date_from: Optional[datetime] = None
    expiry_date_to: Optional[datetime] = None
    search_term: Optional[str] = Field(None, min_length=1, max_length=100)
    expiring_in_days: Optional[int] = Field(None, ge=1, le=365)

    @field_validator("blood_type")
    @classmethod
    def validate_filter_blood_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in BloodType.get_values():
            raise ValueError(
                f'Blood type must be one of: {", ".join(BloodType.get_values())}'
            )
        return v

    @field_validator("blood_product")
    @classmethod
    def validate_filter_blood_product(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if v not in BloodProduct.get_all_accepted_values():
                raise ValueError(
                    f'Blood product must be one of: {", ".join(BloodProduct.get_values())}'
                )
            return BloodProduct.normalize_product_name(v)
        return v


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

    blood_types: Optional[List[str]] = Field(
        None, description="Filter by multiple blood types"
    )
    blood_products: Optional[List[str]] = Field(
        None, description="Filter by multiple blood products"
    )
    min_quantity: Optional[int] = Field(
        None, ge=0, description="Minimum quantity filter"
    )
    max_quantity: Optional[int] = Field(
        None, ge=0, description="Maximum quantity filter"
    )
    expiry_date_from: Optional[date] = Field(
        None, description="Filter by expiry date from"
    )
    expiry_date_to: Optional[date] = Field(None, description="Filter by expiry date to")
    created_from: Optional[datetime] = Field(
        None, description="Filter by creation date from"
    )
    created_to: Optional[datetime] = Field(
        None, description="Filter by creation date to"
    )
    blood_bank_ids: Optional[List[UUID]] = Field(
        None, description="Filter by multiple blood banks"
    )
    search_term: Optional[str] = Field(
        None, min_length=1, max_length=100, description="General search term"
    )

    @field_validator("blood_types")
    @classmethod
    def validate_blood_types(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            valid_types = BloodType.get_values()
            for blood_type in v:
                if blood_type not in valid_types:
                    raise ValueError(f"Invalid blood type: {blood_type}")
        return v

    @field_validator("blood_products")
    @classmethod
    def validate_blood_products(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            normalized_products = []
            for product in v:
                if product not in BloodProduct.get_all_accepted_values():
                    raise ValueError(f"Invalid blood product: {product}")
                normalized_products.append(BloodProduct.normalize_product_name(product))
            return normalized_products
        return v

    @field_validator("max_quantity")
    @classmethod
    def validate_quantity_range(
        cls, v: Optional[int], info: ValidationInfo
    ) -> Optional[int]:
        min_q = info.data.get("min_quantity")
        if v is not None and min_q is not None and v < min_q:
            raise ValueError(
                "max_quantity must be greater than or equal to min_quantity"
            )
        return v

    @field_validator("expiry_date_to")
    @classmethod
    def validate_expiry_date_range(
        cls, v: Optional[date], info: ValidationInfo
    ) -> Optional[date]:
        date_from = info.data.get("expiry_date_from")
        if v is not None and date_from is not None and v < date_from:
            raise ValueError(
                "expiry_date_to must be greater than or equal to expiry_date_from"
            )
        return v

    @field_validator("created_to")
    @classmethod
    def validate_created_date_range(
        cls, v: Optional[datetime], info: ValidationInfo
    ) -> Optional[datetime]:
        created_from = info.data.get("created_from")
        if v is not None and created_from is not None and v < created_from:
            raise ValueError("created_to must be greater than or equal to created_from")
        return v


class FacilityWithBloodAvailability(BaseModel):
    facility_id: UUID
    facility_name: str


class PaginatedFacilityResponse(PaginatedResponse[FacilityWithBloodAvailability]):
    pass


# Utility functions for working with blood data
class BloodCompatibility:
    """Utility class for blood type compatibility checks"""

    DONOR_RECIPIENT_MAP = {
        "O-": ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"],
        "O+": ["O+", "A+", "B+", "AB+"],
        "A-": ["A-", "A+", "AB-", "AB+"],
        "A+": ["A+", "AB+"],
        "B-": ["B-", "B+", "AB-", "AB+"],
        "B+": ["B+", "AB+"],
        "AB-": ["AB-", "AB+"],
        "AB+": ["AB+"],
    }

    @classmethod
    def can_donate_to(cls, donor_type: str, recipient_type: str) -> bool:
        """Check if donor blood type can donate to recipient blood type"""
        if donor_type not in BloodType.get_values():
            raise ValueError(f"Invalid donor blood type: {donor_type}")
        if recipient_type not in BloodType.get_values():
            raise ValueError(f"Invalid recipient blood type: {recipient_type}")

        return recipient_type in cls.DONOR_RECIPIENT_MAP.get(donor_type, [])

    @classmethod
    def get_compatible_donors(cls, recipient_type: str) -> List[str]:
        """Get list of blood types that can donate to the recipient"""
        if recipient_type not in BloodType.get_values():
            raise ValueError(f"Invalid recipient blood type: {recipient_type}")

        compatible_donors = []
        for donor_type, compatible_recipients in cls.DONOR_RECIPIENT_MAP.items():
            if recipient_type in compatible_recipients:
                compatible_donors.append(donor_type)

        return compatible_donors

    @classmethod
    def get_compatible_recipients(cls, donor_type: str) -> List[str]:
        """Get list of blood types that can receive from the donor"""
        if donor_type not in BloodType.get_values():
            raise ValueError(f"Invalid donor blood type: {donor_type}")

        return cls.DONOR_RECIPIENT_MAP.get(donor_type, [])


# Service layer utility functions for better integration
class BloodInventoryServiceUtils:
    """Utility functions for service layer"""

    @staticmethod
    def validate_for_service(
        blood_type: Optional[str] = None, blood_product: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Validate blood attributes for service layer with error details
        Returns a dict with validation results that can be used by the service
        """
        errors = {}

        if blood_type is not None:
            try:
                if blood_type not in BloodType.get_values():
                    errors["blood_type"] = (
                        f"Invalid blood type: {blood_type}. Must be one of: {', '.join(BloodType.get_values())}"
                    )
            except Exception as e:
                errors["blood_type"] = str(e)

        if blood_product is not None:
            try:
                if blood_product not in BloodProduct.get_all_accepted_values():
                    errors["blood_product"] = (
                        f"Invalid blood product: {blood_product}. Must be one of: {', '.join(BloodProduct.get_values())}"
                    )
            except Exception as e:
                errors["blood_product"] = str(e)

        return errors

    @staticmethod
    def normalize_search_params(
        blood_type: Optional[str] = None, blood_product: Optional[str] = None
    ) -> Dict[str, Optional[str]]:
        """Normalize search parameters for consistent querying"""
        result = {}

        if blood_type is not None:
            result["blood_type"] = blood_type

        if blood_product is not None:
            result["blood_product"] = BloodProduct.normalize_product_name(blood_product)

        return result

    @staticmethod
    def get_compatible_blood_types_for_service(recipient_type: str) -> List[str]:
        """Get compatible blood types with service-layer validation"""
        try:
            return BloodCompatibility.get_compatible_donors(recipient_type)
        except ValueError:
            return []


# Enhanced batch operation schemas with service compatibility
class EnhancedBatchOperationResponse(BaseModel):
    """Enhanced batch operation response with detailed error reporting"""

    success: bool
    processed_count: int
    failed_count: int = 0
    errors: List[str] = []
    warnings: List[str] = []  # For non-critical issues like near-expiry dates
    created_ids: Optional[List[UUID]] = None
    updated_ids: Optional[List[UUID]] = None
    validation_errors: Optional[Dict[str, List[str]]] = (
        None  # Detailed validation errors
    )


# Enhanced statistics model for service compatibility
class EnhancedInventoryStatistics(BaseModel):
    """Enhanced inventory statistics with additional metrics"""

    total_units: int
    total_quantity: int
    blood_type_distribution: List[Dict[str, Any]]
    product_distribution: List[Dict[str, Any]]
    expiring_soon: Dict[str, int]

    # Additional metrics for better service integration
    expired_units: Optional[int] = 0
    low_stock_alerts: Optional[List[Dict[str, Any]]] = []
    availability_by_type: Optional[Dict[str, Dict[str, int]]] = None


class BloodTypeOptions(BaseModel):
    """Available blood type options for dropdowns"""

    options: List[str] = Field(default_factory=lambda: BloodType.get_values())


class BloodProductOptions(BaseModel):
    """Available blood product options for dropdowns"""

    options: List[str] = Field(default_factory=lambda: BloodProduct.get_values())


class BloodInventoryDropdownOptions(BaseModel):
    """Combined dropdown options for blood inventory forms"""

    blood_types: List[str] = Field(default_factory=lambda: BloodType.get_values())
    blood_products: List[str] = Field(default_factory=lambda: BloodProduct.get_values())


# Export enums and utility classes for easy importing
__all__ = [
    "BloodType",
    "BloodProduct",
    "SortOrder",
    "BloodCompatibility",
    "BloodInventoryServiceUtils",
    "BloodInventoryCreate",
    "BloodInventoryUpdate",
    "BloodInventoryBatchCreate",
    "BloodInventoryBatchUpdate",
    "BloodInventoryBatchDelete",
    "BloodInventoryResponse",
    "BloodInventoryDetailResponse",
    "PaginationParams",
    "PaginatedResponse",
    "BloodInventoryFilter",
    "BloodInventoryServiceFilter",
    "BatchOperationResponse",
    "EnhancedBatchOperationResponse",
    "InventoryStatistics",
    "EnhancedInventoryStatistics",
    "BloodInventorySearchParams",
    "FacilityWithBloodAvailability",
    "PaginatedFacilityResponse",
    "BloodTypeOptions",
    "BloodProductOptions",
    "BloodInventoryDropdownOptions",
]
