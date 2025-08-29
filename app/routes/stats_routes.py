from app.utils.permission_checker import require_permission
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import date, timedelta

from app.dependencies import get_db
from app.schemas.stats_schema import (
    BloodProductType,
    DashboardSummaryResponse, 
    MonthlyTransferStatsResponse,
    BloodProductBreakdownResponse,
    TransferTrendsResponse
)
from app.services.stats_service import StatsService
from app.models.user import User

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

def get_user_facility_id(current_user: User) -> str:
    """
    Extract facility ID based on user role - handles edge cases.
    Priority: facility_administrator > lab_manager > staff
    """
    user_facility_id = None
    user_role_names = {role.name for role in current_user.roles}  # Use set for faster lookup
    
    # Check roles in priority order
    if "facility_administrator" in user_role_names:
        user_facility_id = current_user.facility.id if current_user.facility else None
        if not user_facility_id:
            raise HTTPException(
                status_code=400, 
                detail="Facility administrator must be associated with a facility"
            )
    
    elif user_role_names & {"lab_manager", "staff"}:  # Intersection check
        user_facility_id = current_user.work_facility_id
        if not user_facility_id:
            raise HTTPException(
                status_code=400, 
                detail="Staff and lab managers must be associated with a work facility"
            )
    
    else:
        # User has roles but none that give facility access
        raise HTTPException(
            status_code=403, 
            detail=f"User roles {list(user_role_names)} do not provide facility access"
        )
    
    return user_facility_id


@router.get("/summary", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    )),
):
    """
    Get dashboard summary for a facility.
    - Total in stock, Total transferred, & Total requested
    - Shape: {
        "total_in_stock": {
            "value": 0,
            "change": 0,
            "direction": "string"
        },
        "total_transferred": {
            "value": 0,
            "change": 0,
            "direction": "string"
        },
        "total_transferred": {
            "value": 0,
            "change": 0,
            "direction": "string"
        },
        "total_requested": {
            "value": 0,
            "change": 0,
            "direction": "string"
        }
    }
    """
    try:
        facility_id = get_user_facility_id(current_user)
        stats_service = StatsService(db)
        data = await stats_service.get_dashboard_summary(facility_id)
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/monthly-transfers", response_model=MonthlyTransferStatsResponse)
async def monthly_transfer_stats(
    year: Optional[int] = Query(None, description="Year to get statistics for (defaults to current year)"),
    blood_product_types: Optional[List[BloodProductType]] = Query(None, description="Filter by specific blood product types"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    )),
):
    """
    Get monthly blood transfer statistics for the current user's facility.

    Provide data for representation on the dashboard graph.
    """
    try:
        facility_id = get_user_facility_id(current_user)
        
        # Default to current year if not provided
        if year is None:
            year = date.today().year
        
        # Validate year range
        current_year = date.today().year
        if year < 2000 or year > current_year + 1:
            raise HTTPException(
                status_code=400, 
                detail=f"Year must be between 2000 and {current_year + 1}"
            )
        
        stats_service = StatsService(db)
        monthly_data = await stats_service.get_monthly_transfer_stats(
            facility_id=facility_id,
            year=year,
            blood_product_types=blood_product_types
        )
        
        # Calculate total units for the year
        total_units_year = sum(month["total_units"] for month in monthly_data)
        
        return MonthlyTransferStatsResponse(
            data=monthly_data,
            total_units_year=total_units_year,
            facility_id=facility_id,
            year=year,
            blood_product_types=blood_product_types
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/blood-product-breakdown", response_model=BloodProductBreakdownResponse)
async def blood_product_breakdown(
    year: Optional[int] = Query(None, description="Year to get statistics for (defaults to current year)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Optional month filter (1-12)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    )),
):
    """
    Breakdown of blood transfers by product type for the current user's facility.
    
    Provides insights into which blood products are most frequently transferred.
    """
    try:
        facility_id = get_user_facility_id(current_user)
        
        # Default to current year if not provided
        if year is None:
            year = date.today().year
        
        # Validate year range
        current_year = date.today().year
        if year < 2024 or year > current_year + 1:
            raise HTTPException(
                status_code=400, 
                detail=f"Year must be between 2024 and {current_year + 1}"
            )
        
        stats_service = StatsService(db)
        breakdown_data = await stats_service.get_blood_product_breakdown(
            facility_id=facility_id,
            year=year,
            month=month
        )
        
        return BloodProductBreakdownResponse(
            data=breakdown_data,
            facility_id=facility_id,
            year=year,
            month=month
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/transfer-trends", response_model=TransferTrendsResponse)
async def transfer_trends(
    days: int = Query(30, ge=1, le=365, description="Number of days to include in the trend (1-365)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    )),
):
    """
    Daily transfer trends for the current user's facility over the last N days.
    
    Useful for creating short-term trend analysis and identifying patterns.
    """
    try:
        facility_id = get_user_facility_id(current_user)
        
        stats_service = StatsService(db)
        trends_data = await stats_service.get_transfer_trends(
            facility_id=facility_id,
            days=days
        )
        
        # Calculate period dates
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        return TransferTrendsResponse(
            data=trends_data,
            facility_id=facility_id,
            days=days,
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")