from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_db
from app.models.user import User
from typing import Optional
from uuid import UUID
from datetime import date, datetime
import logging

from app.schemas.stats_schema import (
    BloodComponentEnum, 
    BloodInventoryTimeSeriesResponse, 
    ComprehensiveDashboardResponse, 
    DashboardSummaryRequest,
    DashboardSummaryResponse, 
    DashboardTimeSeriesRequest, 
    DetailedInventoryStats, 
    HistoricalTrendData, 
    TimeRangeEnum
    )
from app.services.stats_service import DashboardService
from app.utils.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


async def get_user_facility_id(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> UUID:
    """Helper function to get user's facility ID"""
    if current_user.role == 'facility_administrator' and current_user.facility:
        return current_user.facility.id
    elif current_user.work_facility_id:
        return current_user.work_facility_id
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with any facility"
        )


@router.get(
    "/blood-inventory/time-series",
    response_model=BloodInventoryTimeSeriesResponse,
    summary="Get Blood Inventory Time Series Data",
    description="Retrieve time series data for blood inventory tracking (line chart visualization)"
)
async def get_blood_inventory_time_series(
    component: BloodComponentEnum = Query(
        default=BloodComponentEnum.whole_blood,
        description="Blood component to track"
    ),
    time_range: TimeRangeEnum = Query(
        default=TimeRangeEnum.last_30_days,
        description="Time range for the data"
    ),
    start_date: Optional[date] = Query(
        default=None,
        description="Start date (required for custom time range)"
    ),
    end_date: Optional[date] = Query(
        default=None,
        description="End date (required for custom time range)"
    ),
    facility_id: Optional[UUID] = Query(
        default=None,
        description="Facility ID (defaults to current user's facility)"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get blood inventory time series data for dashboard charts.
    
    This endpoint provides data for the line chart showing blood inventory levels over time.
    The data is aggregated daily and includes options for different time ranges and blood components.
    
    **Performance Features:**
    - Optimized queries with proper indexing
    - Date-based aggregation for efficient data retrieval
    - Support for multiple time ranges
    
    **Query Parameters:**
    - component: Type of blood component to track
    - time_range: Predefined time range (last_7_days, last_30_days, etc.)
    - start_date/end_date: Custom date range (when time_range is 'custom')
    - facility_id: Optional facility filter (defaults to user's facility)
    """
    try:
        # Get user's facility if not provided
        user_facility_id = await get_user_facility_id(current_user, db)
        
        # Create request object
        request_params = DashboardTimeSeriesRequest(
            component=component,
            time_range=time_range,
            start_date=start_date,
            end_date=end_date,
            facility_id=facility_id
        )
        
        # Initialize service and get data
        dashboard_service = DashboardService(db)
        result = await dashboard_service.get_blood_inventory_time_series(
            request_params=request_params,
            current_user_facility_id=user_facility_id
        )
        
        logger.info(f"Blood inventory time series retrieved for user {current_user.id}, "
                   f"component {component}, time_range {time_range}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving blood inventory time series: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve blood inventory time series data"
        )


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    summary="Get Dashboard Summary Metrics",
    description="Retrieve daily summary metrics for dashboard KPI cards"
)
async def get_dashboard_summary(
    target_date: Optional[date] = Query(
        default=None,
        description="Target date for metrics (defaults to today)"
    ),
    facility_id: Optional[UUID] = Query(
        default=None,
        description="Facility ID (defaults to current user's facility)"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get dashboard summary with KPI metrics for the dashboard cards.
    
    This endpoint provides the three main KPI metrics:
    - Total Blood in Stock (with percentage change from yesterday)
    - Total Transferred (with percentage change from yesterday)  
    - Total Requests (with percentage change from yesterday)
    
    **Performance Features:**
    - Efficient aggregation queries
    - Automatic calculation of percentage changes
    - Caching of daily summary data
    - Concurrent query execution for optimal performance
    
    **Response includes:**
    - Current day metrics with percentage changes
    - Facility information
    - Last updated timestamp
    """
    try:
        # Get user's facility if not provided
        user_facility_id = await get_user_facility_id(current_user, db)
        
        # Create request object
        request_params = DashboardSummaryRequest(
            facility_id=facility_id,
            target_date=target_date or date.today()
        )
        
        # Initialize service and get data
        dashboard_service = DashboardService(db)
        result = await dashboard_service.get_dashboard_summary(
            request_params=request_params,
            current_user_facility_id=user_facility_id
        )
        
        logger.info(f"Dashboard summary retrieved for user {current_user.id}, "
                   f"facility {result.facility_id}, date {request_params.target_date}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving dashboard summary: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve dashboard summary data"
        )


@router.get(
    "/inventory/detailed-stats",
    response_model=DetailedInventoryStats,
    summary="Get Detailed Inventory Statistics",
    description="Retrieve comprehensive inventory statistics breakdown"
)
async def get_detailed_inventory_stats(
    facility_id: Optional[UUID] = Query(
        default=None,
        description="Facility ID (defaults to current user's facility)"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get detailed inventory statistics with breakdowns by blood type and product.
    
    **Features:**
    - Blood type distribution with available units and expiring units
    - Blood product distribution with available units and expiring units  
    - Total inventory counts
    - Expiration tracking (7 days and 30 days)
    
    **Use Cases:**
    - Detailed inventory analysis
    - Expiration management
    - Blood type/product availability overview
    """
    try:
        # Get user's facility if not provided
        user_facility_id = await get_user_facility_id(current_user, db)
        target_facility_id = facility_id or user_facility_id
        
        # Initialize service and get data
        dashboard_service = DashboardService(db)
        result = await dashboard_service.get_detailed_inventory_stats(target_facility_id)
        
        logger.info(f"Detailed inventory stats retrieved for user {current_user.id}, "
                   f"facility {target_facility_id}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving detailed inventory stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve detailed inventory statistics"
        )


@router.get(
    "/trends/historical",
    response_model=HistoricalTrendData,
    summary="Get Historical Trend Data",
    description="Retrieve historical trend data for dashboard analytics"
)
async def get_historical_trends(
    days: int = Query(
        default=30,
        ge=7,
        le=365,
        description="Number of days to retrieve historical data for"
    ),
    facility_id: Optional[UUID] = Query(
        default=None,
        description="Facility ID (defaults to current user's facility)"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get historical trend data for advanced dashboard analytics.
    
    **Features:**
    - Historical stock levels
    - Transfer volume trends
    - Request count trends
    - Date-aligned data for easy charting
    
    **Parameters:**
    - days: Number of historical days to retrieve (7-365)
    - facility_id: Target facility (defaults to user's facility)
    """
    try:
        # Get user's facility if not provided
        user_facility_id = await get_user_facility_id(current_user, db)
        target_facility_id = facility_id or user_facility_id
        
        # Initialize service and get data
        dashboard_service = DashboardService(db)
        result = await dashboard_service.get_historical_trends(
            facility_id=target_facility_id,
            days=days
        )
        
        logger.info(f"Historical trends retrieved for user {current_user.id}, "
                   f"facility {target_facility_id}, days {days}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving historical trends: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve historical trend data"
        )


@router.get(
    "/comprehensive",
    response_model=ComprehensiveDashboardResponse,
    summary="Get Comprehensive Dashboard Data",
    description="Retrieve all dashboard data in a single optimized request"
)
async def get_comprehensive_dashboard(
    time_range: TimeRangeEnum = Query(
        default=TimeRangeEnum.last_30_days,
        description="Time range for time series data"
    ),
    facility_id: Optional[UUID] = Query(
        default=None,
        description="Facility ID (defaults to current user's facility)"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get comprehensive dashboard data combining all metrics in a single request.
    
    This endpoint is optimized for dashboard pages that need multiple data types:
    - Summary KPI metrics
    - Detailed inventory statistics
    - Historical trend data
    - Time series data for multiple blood components
    
    **Performance Benefits:**
    - Single API call for complete dashboard
    - Concurrent execution of independent queries
    - Optimized data aggregation
    - Reduced network overhead
    
    **Use Case:**
    Perfect for main dashboard pages that display comprehensive blood bank analytics.
    """
    try:
        # Get user's facility if not provided
        user_facility_id = await get_user_facility_id(current_user, db)
        target_facility_id = facility_id or user_facility_id
        
        # Initialize service and get comprehensive data
        dashboard_service = DashboardService(db)
        result = await dashboard_service.get_comprehensive_dashboard(
            facility_id=target_facility_id,
            time_range=time_range
        )
        
        logger.info(f"Comprehensive dashboard data retrieved for user {current_user.id}, "
                   f"facility {target_facility_id}, time_range {time_range}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving comprehensive dashboard data: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve comprehensive dashboard data"
        )


@router.post(
    "/refresh-summary",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Refresh Dashboard Summary Data",
    description="Trigger refresh of dashboard summary data for current date"
)
async def refresh_dashboard_summary(
    background_tasks: BackgroundTasks,
    target_date: Optional[date] = Query(
        default=None,
        description="Date to refresh (defaults to today)"
    ),
    facility_id: Optional[UUID] = Query(
        default=None,
        description="Facility ID (defaults to current user's facility)"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Trigger a refresh of dashboard summary data.
    
    This endpoint recalculates the daily summary metrics for the specified date.
    Useful when real-time data accuracy is critical or after bulk operations.
    
    **Features:**
    - Background processing for better user experience
    - Automatic recalculation of all metrics
    - Updates cached summary data
    
    **Use Cases:**
    - After bulk inventory updates
    - When real-time accuracy is needed
    - Scheduled refresh operations
    """
    try:
        # Get user's facility if not provided
        user_facility_id = await get_user_facility_id(current_user, db)
        target_facility_id = facility_id or user_facility_id
        refresh_date = target_date or date.today()
        
        # Add background task for summary refresh
        background_tasks.add_task(
            _refresh_summary_background,
            db,
            target_facility_id,
            refresh_date,
            current_user.id
        )
        
        logger.info(f"Dashboard summary refresh queued for user {current_user.id}, "
                   f"facility {target_facility_id}, date {refresh_date}")
        
        return {
            "message": "Dashboard summary refresh queued successfully",
            "facility_id": target_facility_id,
            "target_date": refresh_date,
            "status": "processing"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error queueing dashboard summary refresh: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue dashboard summary refresh"
        )


async def _refresh_summary_background(
    db: AsyncSession,
    facility_id: UUID,
    target_date: date,
    user_id: UUID
):
    """Background task to refresh dashboard summary data"""
    try:
        dashboard_service = DashboardService(db)
        
        # Delete existing summary for the date if it exists
        from sqlalchemy import delete
        from app.models.request import DashboardDailySummary
        
        delete_stmt = delete(DashboardDailySummary).where(
            DashboardDailySummary.facility_id == facility_id,
            DashboardDailySummary.date == target_date
        )
        await db.execute(delete_stmt)
        await db.commit()
        
        # Recalculate summary
        await dashboard_service._calculate_daily_summary(facility_id, target_date)
        
        logger.info(f"Dashboard summary refreshed successfully for facility {facility_id}, "
                   f"date {target_date}, requested by user {user_id}")
        
    except Exception as e:
        logger.error(f"Error in background summary refresh: {str(e)}")
        await db.rollback()


# Health check endpoint for dashboard services
@router.get(
    "/health",
    summary="Dashboard Service Health Check",
    description="Check the health status of dashboard services"
)
async def dashboard_health_check(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Health check endpoint for dashboard services.
    
    Verifies:
    - Database connectivity
    - Service initialization
    - Basic query execution
    """
    try:
        dashboard_service = DashboardService(db)
        
        # Simple query to test database connectivity
        from sqlalchemy import text
        result = await db.execute(text("SELECT 1 as health_check"))
        health_check = result.scalar()
        
        return {
            "status": "healthy",
            "database": "connected" if health_check == 1 else "disconnected",
            "service": "initialized",
            "timestamp": datetime.now().isoformat(),
            "user_id": current_user.id
        }
        
    except Exception as e:
        logger.error(f"Dashboard health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }