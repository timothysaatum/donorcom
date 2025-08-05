from pydantic import BaseModel, Field, validator
from datetime import datetime, date
from typing import List, Optional, Dict
from enum import Enum
import uuid


class TimeRangeEnum(str, Enum):
    """Time range options for dashboard queries"""
    last_7_days = "last_7_days"
    last_30_days = "last_30_days" 
    last_90_days = "last_90_days"
    last_6_months = "last_6_months"
    last_year = "last_year"
    custom = "custom"


class BloodComponentEnum(str, Enum):
    """Blood components for tracking"""
    whole_blood = "Whole Blood"
    red_blood_cells = "Red Blood Cells"
    platelets = "Platelets"
    fresh_frozen_plasma = "Fresh Frozen Plasma"
    cryoprecipitate = "Cryoprecipitate"
    albumin = "Albumin"


class ChartDataPoint(BaseModel):
    """Individual data point for charts"""
    date: date
    value: int = Field(..., ge=0, description="Quantity value")
    
    class Config:
        json_encoders = {
            date: lambda v: v.isoformat()
        }


class BloodInventoryTimeSeriesResponse(BaseModel):
    """Response for blood inventory time series data"""
    component: BloodComponentEnum
    data_points: List[ChartDataPoint]
    total_records: int = Field(..., ge=0)
    date_range: Dict[str, date]
    
    class Config:
        json_encoders = {
            date: lambda v: v.isoformat()
        }


class DashboardTimeSeriesRequest(BaseModel):
    """Request parameters for time series data"""
    component: BloodComponentEnum = Field(default=BloodComponentEnum.whole_blood)
    time_range: TimeRangeEnum = Field(default=TimeRangeEnum.last_30_days)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    facility_id: Optional[uuid.UUID] = None
    
    @validator('end_date')
    def validate_date_range(cls, v, values):
        if values.get('time_range') == TimeRangeEnum.custom:
            start_date = values.get('start_date')
            if not start_date or not v:
                raise ValueError("start_date and end_date are required for custom time range")
            if start_date >= v:
                raise ValueError("start_date must be before end_date")
            if (v - start_date).days > 365:
                raise ValueError("Date range cannot exceed 365 days")
        return v
    
    class Config:
        json_encoders = {
            date: lambda v: v.isoformat()
        }


class DailySummaryMetrics(BaseModel):
    """Daily summary metrics model"""
    total_stock: int = Field(..., ge=0, description="Total blood units in stock")
    total_transferred: int = Field(..., ge=0, description="Total units transferred")
    total_requests: int = Field(..., ge=0, description="Total requests made")
    stock_change_percent: float = Field(description="Percentage change from previous day")
    transfer_change_percent: float = Field(description="Percentage change from previous day")
    request_change_percent: float = Field(description="Percentage change from previous day")
    date: datetime = Field(description="Date of the metrics")
    
    class Config:
        json_encoders = {
            date: lambda v: v.isoformat()
        }


class DashboardSummaryResponse(BaseModel):
    """Response for dashboard summary data"""
    current_metrics: DailySummaryMetrics
    facility_id: uuid.UUID
    facility_name: str
    last_updated: datetime
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            date: lambda v: v.isoformat()
        }


class DashboardSummaryRequest(BaseModel):
    """Request parameters for dashboard summary"""
    facility_id: Optional[uuid.UUID] = None
    target_date: Optional[date] = Field(default_factory=date.today)
    
    class Config:
        json_encoders = {
            date: lambda v: v.isoformat()
        }


class BloodAvailabilityByType(BaseModel):
    """Blood availability breakdown by blood type"""
    blood_type: str
    available_units: int = Field(..., ge=0)
    expiring_soon: int = Field(..., ge=0, description="Units expiring in next 7 days")
    

class BloodAvailabilityByProduct(BaseModel):
    """Blood availability breakdown by product type"""
    blood_product: str
    available_units: int = Field(..., ge=0)
    expiring_soon: int = Field(..., ge=0)


class DetailedInventoryStats(BaseModel):
    """Detailed inventory statistics"""
    total_units: int = Field(..., ge=0)
    by_blood_type: List[BloodAvailabilityByType]
    by_product: List[BloodAvailabilityByProduct]
    expiring_in_7_days: int = Field(..., ge=0)
    expiring_in_30_days: int = Field(..., ge=0)
    
    
class HistoricalTrendData(BaseModel):
    """Historical trend data for dashboard"""
    dates: List[date]
    stock_levels: List[int]
    transfer_volumes: List[int] 
    request_counts: List[int]
    
    class Config:
        json_encoders = {
            date: lambda v: v.isoformat()
        }


class ComprehensiveDashboardResponse(BaseModel):
    """Comprehensive dashboard response with all data"""
    summary: DashboardSummaryResponse
    inventory_stats: DetailedInventoryStats
    historical_trends: HistoricalTrendData
    time_series_data: List[BloodInventoryTimeSeriesResponse]
    
    
class FacilityDashboardFilter(BaseModel):
    """Filter parameters for facility dashboard"""
    facility_ids: Optional[List[uuid.UUID]] = None
    include_expired: bool = Field(default=False)
    blood_types: Optional[List[str]] = None
    blood_products: Optional[List[str]] = None