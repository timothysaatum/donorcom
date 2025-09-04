from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date
from uuid import UUID


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
    data: List[MonthlyTransferData] = Field(..., description="Monthly transfer statistics")
    total_units_year: int = Field(..., description="Total units transferred in the year")
    facility_id: UUID = Field(..., description="Facility ID")
    year: int = Field(..., description="Year of the statistics")
    blood_product_types: Optional[List[str]] = Field(None, description="Filtered blood product types")


class BloodProductBreakdown(BaseModel):
    blood_product: str = Field(..., description="Blood product type")
    total_units: int = Field(..., description="Total units of this product")
    total_transfers: int = Field(..., description="Number of transfers for this product")


class BloodProductBreakdownResponse(BaseModel):
    data: List[BloodProductBreakdown] = Field(..., description="Blood product breakdown")
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