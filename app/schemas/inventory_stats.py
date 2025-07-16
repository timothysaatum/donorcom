from pydantic import BaseModel, Field
from datetime import datetime
# from typing import Optional, Dict, Any
from enum import Enum


class StatsTimeframe(str, Enum):
    """Timeframe options for statistics comparison"""
    TODAY = "today"
    YESTERDAY = "yesterday"
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    LAST_90_DAYS = "last_90_days"


class TrendData(BaseModel):
    """Model for trend information"""
    current_value: int = Field(..., description="Current value")
    previous_value: int = Field(..., description="Previous value for comparison")
    percentage_change: float = Field(..., description="Percentage change from previous period")
    is_increase: bool = Field(..., description="Whether the change is an increase")
    
    class Config:
        json_encoders = {
            float: lambda v: round(v, 2)
        }


class BloodTypeStats(BaseModel):
    """Statistics for a specific blood type"""
    blood_type: str = Field(..., description="Blood type (e.g., A+, B-, O+)")
    current_stock: int = Field(..., description="Current stock units")
    total_requests: int = Field(..., description="Total requests for this blood type")
    total_transferred: int = Field(..., description="Total units transferred")
    expiring_soon: int = Field(..., description="Units expiring within 7 days")
    expired: int = Field(..., description="Expired units")


class BloodProductStats(BaseModel):
    """Statistics for a specific blood product"""
    blood_product: str = Field(..., description="Blood product type")
    current_stock: int = Field(..., description="Current stock units")
    total_requests: int = Field(..., description="Total requests for this product")
    total_transferred: int = Field(..., description="Total units transferred")
    expiring_soon: int = Field(..., description="Units expiring within 7 days")


class InventoryStatsResponse(BaseModel):
    """Main response model for inventory statistics"""
    total_blood_in_stock: TrendData = Field(..., description="Total blood units in stock")
    total_transferred: TrendData = Field(..., description="Total units transferred")
    total_requests: TrendData = Field(..., description="Total blood requests")
    
    # Additional detailed stats
    low_stock_items: int = Field(..., description="Items with low stock (< 10 units)")
    expiring_soon: int = Field(..., description="Units expiring within 7 days")
    expired_units: int = Field(..., description="Expired units")
    
    # Breakdown by blood type and product
    blood_type_breakdown: list[BloodTypeStats] = Field(..., description="Stats by blood type")
    blood_product_breakdown: list[BloodProductStats] = Field(..., description="Stats by blood product")
    
    # Meta information
    last_updated: datetime = Field(..., description="When stats were last calculated")
    timeframe: StatsTimeframe = Field(..., description="Timeframe used for comparison")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class FacilityStatsResponse(BaseModel):
    """Statistics response for facility-level data"""
    facility_id: str = Field(..., description="Facility ID")
    facility_name: str = Field(..., description="Facility name")
    inventory_stats: InventoryStatsResponse = Field(..., description="Inventory statistics")
    
    # Facility-specific metrics
    total_blood_banks: int = Field(..., description="Number of blood banks in facility")
    active_requests: int = Field(..., description="Active blood requests")
    pending_transfers: int = Field(..., description="Pending transfers")


class SystemWideStatsResponse(BaseModel):
    """System-wide statistics response"""
    total_facilities: int = Field(..., description="Total number of facilities")
    total_blood_banks: int = Field(..., description="Total number of blood banks")
    system_inventory: InventoryStatsResponse = Field(..., description="System-wide inventory stats")
    
    # Network metrics
    inter_facility_transfers: int = Field(..., description="Transfers between facilities")
    network_efficiency: float = Field(..., description="Network efficiency score")
    
    class Config:
        json_encoders = {
            float: lambda v: round(v, 2)
        }