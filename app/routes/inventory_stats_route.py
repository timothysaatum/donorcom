from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, and_, select, distinct
from app.dependencies import get_db
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest
from app.models.health_facility import Facility
from app.models.user import User
from app.models.blood_bank import BloodBank
from app.utils.security import get_current_user
from app.services.inventory_stats_service import DashboardStatsService
import logging

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/stats",
    tags=["stats"]
)



@router.get("/dashboard/stats")
async def get_dashboard_stats(
    target_date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get dashboard statistics for the current user's facility
    
    Args:
        target_date: Optional date string (YYYY-MM-DD). Defaults to today.
        
    Returns:
        Dashboard statistics including blood stock, transfers, and requests
    """
    try:
        # Parse target date
        parsed_date = None
        if target_date:
            try:
                parsed_date = date.fromisoformat(target_date)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid date format. Use YYYY-MM-DD"
                )
        
        # Get stats using service
        service = DashboardStatsService(db)
        stats = await service.get_facility_stats(
            user=current_user,
            target_date=parsed_date
        )
        
        return {
            "success": True,
            "data": stats,
            "message": "Dashboard statistics retrieved successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error while fetching dashboard statistics"
        )


@router.get("/dashboard/stats/detailed")
async def get_detailed_dashboard_stats(
    target_date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed dashboard statistics with breakdown by blood type
    """
    try:
        parsed_date = date.today()
        if target_date:
            try:
                parsed_date = date.fromisoformat(target_date)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid date format. Use YYYY-MM-DD"
                )
        
        service = DashboardStatsService(db)
        facility_id = await service._get_user_facility_id(current_user)
        
        if not facility_id:
            raise HTTPException(
                status_code=400,
                detail="User is not associated with any facility"
            )
        
        # Get blood bank for this facility
        blood_bank_query = select(BloodBank.id).where(BloodBank.facility_id == facility_id)
        result = await db.execute(blood_bank_query)
        blood_bank_id = result.scalar_one_or_none()
        
        # Blood stock by type
        stock_breakdown = []
        if blood_bank_id:
            stock_query = select(
                BloodInventory.blood_type,
                BloodInventory.blood_product,
                func.sum(BloodInventory.quantity).label('total_quantity')
            ).where(
                and_(
                    BloodInventory.blood_bank_id == blood_bank_id,
                    BloodInventory.expiry_date > parsed_date
                )
            ).group_by(BloodInventory.blood_type, BloodInventory.blood_product)
            
            result = await db.execute(stock_query)
            stock_by_type = result.fetchall()
            
            stock_breakdown = [
                {
                    "blood_type": item.blood_type,
                    "blood_product": item.blood_product,
                    "quantity": item.total_quantity
                }
                for item in stock_by_type
            ]
        
        # Requests by status
        requests_query = select(
            BloodRequest.request_status,
            func.count(distinct(BloodRequest.id)).label('count'),
            func.sum(BloodRequest.quantity_requested).label('total_quantity')
        ).where(
            and_(
                BloodRequest.facility_id == facility_id,
                func.date(BloodRequest.created_at) == parsed_date
            )
        ).group_by(BloodRequest.request_status)
        
        result = await db.execute(requests_query)
        requests_by_status = result.fetchall()
        
        requests_breakdown = [
            {
                "status": item.request_status.value,
                "count": item.count,
                "total_quantity": item.total_quantity or 0
            }
            for item in requests_by_status
        ]
        
        # Get basic stats
        basic_stats = await service.get_facility_stats(current_user, parsed_date)
        
        return {
            "success": True,
            "data": {
                **basic_stats,
                "stock_breakdown": stock_breakdown,
                "requests_breakdown": requests_breakdown
            },
            "message": "Detailed dashboard statistics retrieved successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting detailed dashboard stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error while fetching detailed dashboard statistics"
        )


@router.post("/dashboard/refresh-cache")
async def refresh_dashboard_cache(
    target_date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually refresh the dashboard cache for a specific date
    Useful for background jobs or manual cache updates
    """
    try:
        parsed_date = date.today()
        if target_date:
            try:
                parsed_date = date.fromisoformat(target_date)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid date format. Use YYYY-MM-DD"
                )
        
        service = DashboardStatsService(db)
        facility_id = await service._get_user_facility_id(current_user)
        
        if not facility_id:
            raise HTTPException(
                status_code=400,
                detail="User is not associated with any facility"
            )
        
        await service.update_daily_summary(
            facility_id=facility_id,
            target_date=parsed_date
        )
        
        return {
            "success": True,
            "message": f"Dashboard cache refreshed for {parsed_date}",
            "date": parsed_date.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing dashboard cache: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error while refreshing dashboard cache"
        )


# Background job function (can be called by Celery or similar)
async def refresh_all_facilities_cache(db: AsyncSession, target_date: Optional[date] = None):
    """
    Background job to refresh dashboard cache for all facilities
    """
    if target_date is None:
        target_date = date.today()
    
    # Get all facility IDs
    facilities_query = select(Facility.id)
    result = await db.execute(facilities_query)
    facility_ids = [row[0] for row in result.fetchall()]
    
    service = DashboardStatsService(db)
    
    for facility_id in facility_ids:
        try:
            await service.update_daily_summary(facility_id, target_date)
            logger.info(f"Updated dashboard cache for facility {facility_id}")
        except Exception as e:
            logger.error(f"Failed to update cache for facility {facility_id}: {str(e)}")
    
    logger.info(f"Completed dashboard cache refresh for {len(facility_ids)} facilities")