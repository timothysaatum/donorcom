from pydantic import BaseModel, Field, validator
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum
from uuid import UUID


class BloodProduct(str, Enum):
    """Blood product options for API."""

    whole_blood = "whole_blood"
    red_blood_cells = "red_blood_cells"
    platelets = "platelets"
    fresh_frozen_plasma = "fresh_frozen_plasma"
    cryoprecipitate = "cryoprecipitate"
    albumin = "albumin"


class BloodType(str, Enum):
    """Blood type options for API."""

    A_positive = "A+"
    A_negative = "A-"
    B_positive = "B+"
    B_negative = "B-"
    AB_positive = "AB+"
    AB_negative = "AB-"
    O_positive = "O+"
    O_negative = "O-"


class Priority(str, Enum):
    """Priority options for API."""

    urgent = "urgent"
    not_urgent = "not urgent"


class RequestDirection(str, Enum):
    """Request direction options for API."""

    sent = "sent"
    received = "received"


class RequestChartFilters(BaseModel):
    """Filters for request chart data."""

    from_date: Optional[datetime] = Field(
        None, description="Start date for filtering (defaults to 7 days ago)"
    )
    to_date: Optional[datetime] = Field(
        None, description="End date for filtering (defaults to today)"
    )
    selected_blood_products: Optional[List[BloodProduct]] = Field(
        None,
        description="List of blood products to include (defaults to whole_blood, red_blood_cells, platelets)",
    )
    selected_blood_types: Optional[List[BloodType]] = Field(
        None, description="List of blood types to filter by"
    )
    request_direction: Optional[RequestDirection] = Field(
        None, description="Filter by sent or received requests (defaults to both)"
    )
    selected_priorities: Optional[List[Priority]] = Field(
        None, description="List of priorities to filter by"
    )

    @validator("from_date", "to_date")
    def validate_dates(cls, v):
        """Validate date inputs."""
        if v and v > datetime.now():
            raise ValueError("Date cannot be in the future")
        return v

    @validator("to_date")
    def validate_date_range(cls, v, values):
        """Validate that to_date is after from_date."""
        if v and "from_date" in values and values["from_date"]:
            if v <= values["from_date"]:
                raise ValueError("to_date must be after from_date")

            # Check for reasonable date range
            date_diff = (v - values["from_date"]).days
            if date_diff > 365:
                raise ValueError("Date range cannot exceed 365 days")
        return v


class RequestChartRequest(BaseModel):
    """Request model for getting request chart data."""

    facility_id: UUID = Field(
        ..., description="The facility ID to get request data for"
    )
    filters: Optional[RequestChartFilters] = Field(
        None, description="Optional filters for the chart data"
    )


class RequestChartDataPoint(BaseModel):
    """Single data point in request chart."""

    date: str = Field(..., description="ISO date string with timezone")
    formattedDate: str = Field(
        ..., description="Human-readable date format (e.g., 'Jan 15')"
    )
    whole_blood: Optional[int] = Field(
        None, description="Whole blood requests for this date"
    )
    red_blood_cells: Optional[int] = Field(
        None, description="Red blood cell requests for this date"
    )
    platelets: Optional[int] = Field(
        None, description="Platelet requests for this date"
    )
    fresh_frozen_plasma: Optional[int] = Field(
        None, description="Fresh frozen plasma requests for this date"
    )
    cryoprecipitate: Optional[int] = Field(
        None, description="Cryoprecipitate requests for this date"
    )
    albumin: Optional[int] = Field(None, description="Albumin requests for this date")

    class Config:
        # Allow extra fields for dynamic blood products
        extra = "allow"


class RequestChartMetadata(BaseModel):
    """Metadata for request chart response."""

    totalRecords: int = Field(..., description="Total number of data points")
    dateRange: Dict[str, str] = Field(..., description="Date range used for the chart")
    bloodProducts: List[str] = Field(
        ..., description="Blood products included in the chart"
    )
    bloodTypes: Optional[List[str]] = Field(None, description="Blood types filtered")


class RequestChartResponse(BaseModel):
    """Response model for request chart data."""

    success: bool = Field(True, description="Whether the request was successful")
    data: List[RequestChartDataPoint] = Field(
        ..., description="List of daily request data points"
    )
    meta: RequestChartMetadata = Field(..., description="Metadata about the chart data")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class Metric(BaseModel):
    value: int
    change: float
    direction: str


class BloodProductType(str, Enum):
    whole_blood = "Whole Blood"
    red_blood_cells = "Red Blood Cells"
    plasma = "Plasma"
    platelets = "Platelets"
    cryoprecipitate = "Cryoprecipitate"
    fresh_frozen_plasma = "Fresh Frozen Plasma"
    albumin = "Albumin"
    red_cells = "Red Cells"


# Add BloodType enum for blood type filtering
class BloodType(str, Enum):
    a_positive = "A+"
    a_negative = "A-"
    b_positive = "B+"
    b_negative = "B-"
    ab_positive = "AB+"
    ab_negative = "AB-"
    o_positive = "O+"
    o_negative = "O-"


class DashboardSummaryResponse(BaseModel):
    stock: Metric
    transferred: Metric
    requests: Metric


class MonthlyTransferData(BaseModel):
    month: str = Field(..., description="Full month name (e.g., 'January')")
    month_number: int = Field(..., description="Month number (1-12)")
    total_units: int = Field(..., description="Total blood units transferred")
    year: int = Field(..., description="Year of the data")


class MonthlyTransferStatsResponse(BaseModel):
    data: List[MonthlyTransferData] = Field(
        ..., description="Monthly transfer statistics"
    )
    total_units_year: int = Field(
        ..., description="Total units transferred in the year"
    )
    facility_id: UUID = Field(..., description="Facility ID")
    year: int = Field(..., description="Year of the statistics")
    blood_product_types: Optional[List[str]] = Field(
        None, description="Filtered blood product types"
    )


class BloodProductBreakdown(BaseModel):
    blood_product: str = Field(..., description="Blood product type")
    total_units: int = Field(..., description="Total units of this product")
    total_transfers: int = Field(
        ..., description="Number of transfers for this product"
    )


class BloodProductBreakdownResponse(BaseModel):
    data: List[BloodProductBreakdown] = Field(
        ..., description="Blood product breakdown"
    )
    facility_id: UUID = Field(..., description="Facility ID")
    year: int = Field(..., description="Year of the statistics")
    month: Optional[int] = Field(None, description="Month filter if applied")


class DailyTransferTrend(BaseModel):
    date: str = Field(..., description="Date in ISO format (YYYY-MM-DD)")
    total_units: int = Field(..., description="Total units transferred on this date")
    total_transfers: int = Field(..., description="Number of transfers on this date")


class TransferTrendsResponse(BaseModel):
    data: List[DailyTransferTrend] = Field(..., description="Daily transfer trends")
    facility_id: UUID = Field(..., description="Facility ID")
    days: int = Field(..., description="Number of days included in the trend")
    period_start: str = Field(..., description="Start date of the period")
    period_end: str = Field(..., description="End date of the period")


class ChartDataPoint(BaseModel):
    date: str  # ISO 8601 format
    formattedDate: str  # Display format like "Sep 04"
    whole_blood: Optional[int] = None
    red_blood_cells: Optional[int] = None
    platelets: Optional[int] = None
    fresh_frozen_plasma: Optional[int] = None
    cryoprecipitate: Optional[int] = None
    albumin: Optional[int] = None

    class Config:
        # Allow extra fields for dynamic blood products
        extra = "allow"


class ChartMetadata(BaseModel):
    totalRecords: int
    dateRange: Dict[str, str]  # {"from": "ISO date", "to": "ISO date"}
    bloodProducts: List[str]
    bloodTypes: Optional[List[str]] = Field(
        None, description="Filtered blood types"
    )  # Add blood types


class DistributionChartResponse(BaseModel):
    success: bool
    data: List[ChartDataPoint]
    meta: ChartMetadata
