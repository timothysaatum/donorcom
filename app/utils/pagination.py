# Create pagination dependency
from typing import Annotated, Generic, List, Optional, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.base_schema import SortOrder


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


def get_pagination_params(
    page: Annotated[int, Query(ge=1, description="Page number (1-based)")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=100, description="Items per page (max 100)")
    ] = 20,
    sort_by: Annotated[Optional[str], Query(description="Field to sort by")] = None,
    sort_order: Annotated[
        str, Query(pattern="^(asc|desc)$", description="Sort order")
    ] = "desc",
) -> PaginationParams:
    return PaginationParams(
        page=page, page_size=page_size, sort_by=sort_by, sort_order=sort_order
    )
