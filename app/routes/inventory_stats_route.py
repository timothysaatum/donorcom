from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional, Dict, Any
from app.dependencies import get_db
from app.utils.security import get_current_user
from app.models.user import User
from app.services.inventory_stats_service import BloodInventoryStatsService
from app.schemas.inventory_stats import (
    InventoryStatsResponse,
    FacilityStatsResponse,
    SystemWideStatsResponse,
    StatsTimeframe
)
from fastapi.responses import JSONResponse
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/stats",
    tags=["statistics"]
)


@router.get("/inventory", response_model=InventoryStatsResponse)
async def get_inventory_statistics(
    timeframe: StatsTimeframe = Query(
        StatsTimeframe.YESTERDAY,
        description="Timeframe for statistics comparison"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get comprehensive inventory statistics for the current user's facility.
    
    This endpoint provides the main dashboard statistics including:
    - Total blood in stock with trend analysis
    - Total transferred units with trend analysis  
    - Total requests with trend analysis
    - Low stock alerts
    - Expiring soon alerts
    - Breakdown by blood type and product
    
    The trends are calculated by comparing current period with previous period
    of the same duration.
    """
    try:
        service = BloodInventoryStatsService(db)
        stats = await service.get_facility_stats(
            user_id=current_user.id,
            timeframe=timeframe
        )
        
        logger.info(f"Inventory statistics retrieved for user {current_user.id}")
        return stats
        
    except Exception as e:
        logger.error(f"Error retrieving inventory statistics: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve inventory statistics"
        )


@router.get("/inventory/blood-types", response_model=list[dict])
async def get_blood_type_statistics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get detailed statistics breakdown by blood type.
    
    Returns current stock, requests, transfers, and expiry information
    for each blood type in the user's facility.
    """
    try:
        service = BloodInventoryStatsService(db)
        facility_id = await service._get_user_facility_id(current_user.id)
        
        if not facility_id:
            raise HTTPException(status_code=404, detail="User facility not found")
        
        blood_type_stats = await service._get_blood_type_breakdown(facility_id)
        
        return [stat.dict() for stat in blood_type_stats]
        
    except Exception as e:
        logger.error(f"Error retrieving blood type statistics: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve blood type statistics"
        )


@router.get("/inventory/blood-products", response_model=list[dict])
async def get_blood_product_statistics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get detailed statistics breakdown by blood product.
    
    Returns current stock, requests, transfers, and expiry information
    for each blood product type in the user's facility.
    """
    try:
        service = BloodInventoryStatsService(db)
        facility_id = await service._get_user_facility_id(current_user.id)
        
        if not facility_id:
            raise HTTPException(status_code=404, detail="User facility not found")
        
        blood_product_stats = await service._get_blood_product_breakdown(facility_id)
        
        return [stat.dict() for stat in blood_product_stats]
        
    except Exception as e:
        logger.error(f"Error retrieving blood product statistics: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve blood product statistics"
        )


@router.get("/inventory/alerts")
async def get_inventory_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get inventory alerts for low stock and expiring items.
    
    Returns:
    - Items with low stock (< 10 units)
    - Items expiring within 7 days
    - Already expired items
    """
    try:
        service = BloodInventoryStatsService(db)
        facility_id = await service._get_user_facility_id(current_user.id)
        
        if not facility_id:
            raise HTTPException(status_code=404, detail="User facility not found")
        
        from datetime import date, timedelta
        from sqlalchemy import text
        
        # Get detailed alert information
        query = text("""
            WITH facility_blood_banks AS (
                SELECT id FROM blood_banks WHERE facility_id = :facility_id
            )
            SELECT 
                bi.id,
                bi.blood_type,
                bi.blood_product,
                bi.quantity,
                bi.expiry_date,
                bb.blood_bank_name,
                CASE 
                    WHEN bi.quantity < 10 THEN 'low_stock'
                    WHEN bi.expiry_date <= CURRENT_DATE THEN 'expired'
                    WHEN bi.expiry_date <= CURRENT_DATE + INTERVAL '7 days' THEN 'expiring_soon'
                    ELSE 'normal'
                END as alert_type
            FROM blood_inventory bi
            JOIN blood_banks bb ON bi.blood_bank_id = bb.id
            WHERE bi.blood_bank_id IN (SELECT id FROM facility_blood_banks)
            AND (
                bi.quantity < 10 
                OR bi.expiry_date <= CURRENT_DATE + INTERVAL '7 days'
            )
            ORDER BY bi.expiry_date ASC, bi.quantity ASC
        """)
        
        result = await db.execute(query, {'facility_id': str(facility_id)})
        
        alerts = []
        for row in result.fetchall():
            alerts.append({
                'id': str(row[0]),
                'blood_type': row[1],
                'blood_product': row[2],
                'quantity': row[3],
                'expiry_date': row[4].isoformat() if row[4] else None,
                'blood_bank_name': row[5],
                'alert_type': row[6],
                'priority': 'high' if row[6] == 'expired' else 'medium' if row[6] == 'expiring_soon' else 'low'
            })
        
        return {
            'alerts': alerts,
            'total_alerts': len(alerts),
            'alert_summary': {
                'low_stock': len([a for a in alerts if a['alert_type'] == 'low_stock']),
                'expiring_soon': len([a for a in alerts if a['alert_type'] == 'expiring_soon']),
                'expired': len([a for a in alerts if a['alert_type'] == 'expired'])
            }
        }
        
    except Exception as e:
        logger.error(f"Error retrieving inventory alerts: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve inventory alerts"
        )


@router.get("/blood-bank/{blood_bank_id}")
async def get_blood_bank_statistics(
    blood_bank_id: UUID = Path(..., description="Blood bank ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get detailed statistics for a specific blood bank.
    
    This endpoint provides comprehensive statistics for a single blood bank,
    including inventory levels, stock alerts, and performance metrics.
    """
    try:
        service = BloodInventoryStatsService(db)
        
        # Verify user has access to this blood bank
        facility_id = await service._get_user_facility_id(current_user.id)
        if not facility_id:
            raise HTTPException(status_code=404, detail="User facility not found")
        
        # Verify blood bank belongs to user's facility
        from sqlalchemy import select
        from app.models.blood_bank import BloodBank
        
        result = await db.execute(
            select(BloodBank).where(
                BloodBank.id == blood_bank_id,
                BloodBank.facility_id == facility_id
            )
        )
        blood_bank = result.scalar_one_or_none()
        
        if not blood_bank:
            raise HTTPException(
                status_code=404,
                detail="Blood bank not found or access denied"
            )
        
        stats = await service.get_blood_bank_stats(blood_bank_id)
        
        return {
            'blood_bank_id': str(blood_bank_id),
            'blood_bank_name': blood_bank.blood_bank_name,
            'statistics': stats
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving blood bank statistics: {str(e)}")
