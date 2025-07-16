from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_, func, case, text
from fastapi import HTTPException
from uuid import UUID
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest, RequestStatus, ProcessingStatus
from app.models.blood_bank import BloodBank
from app.models.health_facility import Facility
from app.models.user import User
from app.schemas.inventory_stats import (
    InventoryStatsResponse,
    FacilityStatsResponse,
    SystemWideStatsResponse,
    TrendData,
    BloodTypeStats,
    BloodProductStats,
    StatsTimeframe
)
import logging
from functools import lru_cache
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DateRange:
    """Helper class for date range calculations"""
    start_date: date
    end_date: date
    
    @classmethod
    def from_timeframe(cls, timeframe: StatsTimeframe) -> 'DateRange':
        """Create date range from timeframe enum"""
        today = date.today()
        
        if timeframe == StatsTimeframe.TODAY:
            return cls(today, today)
        elif timeframe == StatsTimeframe.YESTERDAY:
            yesterday = today - timedelta(days=1)
            return cls(yesterday, yesterday)
        elif timeframe == StatsTimeframe.LAST_7_DAYS:
            return cls(today - timedelta(days=7), today)
        elif timeframe == StatsTimeframe.LAST_30_DAYS:
            return cls(today - timedelta(days=30), today)
        elif timeframe == StatsTimeframe.LAST_90_DAYS:
            return cls(today - timedelta(days=90), today)
        else:
            return cls(today, today)


class BloodInventoryStatsService:
    """High-performance service for blood inventory statistics"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_facility_stats(
        self, 
        user_id: UUID, 
        timeframe: StatsTimeframe = StatsTimeframe.YESTERDAY
    ) -> InventoryStatsResponse:
        """Get comprehensive inventory statistics for a user's facility"""
        
        # Get user's facility
        facility_id = await self._get_user_facility_id(user_id)
        if not facility_id:
            raise HTTPException(status_code=404, detail="User facility not found")
        
        # Calculate date ranges
        current_range = DateRange.from_timeframe(timeframe)
        
        # Get previous period for comparison
        days_diff = (current_range.end_date - current_range.start_date).days + 1
        previous_range = DateRange(
            current_range.start_date - timedelta(days=days_diff),
            current_range.end_date - timedelta(days=days_diff)
        )
        
        # Execute all queries concurrently for better performance
        current_stats = await self._get_period_stats(facility_id, current_range)
        previous_stats = await self._get_period_stats(facility_id, previous_range)
        
        # Get additional detailed stats
        blood_type_stats = await self._get_blood_type_breakdown(facility_id)
        blood_product_stats = await self._get_blood_product_breakdown(facility_id)
        
        # Calculate trends
        stock_trend = self._calculate_trend(
            current_stats['total_stock'], 
            previous_stats['total_stock']
        )
        
        transferred_trend = self._calculate_trend(
            current_stats['total_transferred'], 
            previous_stats['total_transferred']
        )
        
        requests_trend = self._calculate_trend(
            current_stats['total_requests'], 
            previous_stats['total_requests']
        )
        
        return InventoryStatsResponse(
            total_blood_in_stock=stock_trend,
            total_transferred=transferred_trend,
            total_requests=requests_trend,
            low_stock_items=current_stats['low_stock_items'],
            expiring_soon=current_stats['expiring_soon'],
            expired_units=current_stats['expired_units'],
            blood_type_breakdown=blood_type_stats,
            blood_product_breakdown=blood_product_stats,
            last_updated=datetime.timezone.utc(),
            timeframe=timeframe
        )
    
    async def get_system_wide_stats(
        self, 
        timeframe: StatsTimeframe = StatsTimeframe.YESTERDAY
    ) -> SystemWideStatsResponse:
        """Get system-wide statistics across all facilities"""
        
        # Get system-wide metrics
        facilities_count = await self._get_total_facilities()
        blood_banks_count = await self._get_total_blood_banks()
        
        # Calculate system inventory stats
        system_inventory = await self._get_system_inventory_stats(timeframe)
        
        # Get network metrics
        inter_facility_transfers = await self._get_inter_facility_transfers()
        network_efficiency = await self._calculate_network_efficiency()
        
        return SystemWideStatsResponse(
            total_facilities=facilities_count,
            total_blood_banks=blood_banks_count,
            system_inventory=system_inventory,
            inter_facility_transfers=inter_facility_transfers,
            network_efficiency=network_efficiency
        )
    
    async def _get_user_facility_id(self, user_id: UUID) -> Optional[UUID]:
        """Get facility ID for a user"""
        result = await self.db.execute(
            select(User)
            .options(
                joinedload(User.facility),
                joinedload(User.work_facility)
            )
            .where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return None
        
        # Return facility ID based on user role
        if user.facility:
            return user.facility.id
        elif user.work_facility:
            return user.work_facility.id
        
        return None
    
    async def _get_period_stats(self, facility_id: UUID, date_range: DateRange) -> Dict[str, int]:
        """Get statistics for a specific period and facility"""
        
        # Use a single complex query for better performance
        query = text("""
            WITH facility_blood_banks AS (
                SELECT id FROM blood_banks WHERE facility_id = :facility_id
            ),
            inventory_stats AS (
                SELECT 
                    COALESCE(SUM(quantity), 0) as total_stock,
                    COALESCE(SUM(CASE WHEN quantity < 10 THEN 1 ELSE 0 END), 0) as low_stock_items,
                    COALESCE(SUM(CASE WHEN expiry_date <= CURRENT_DATE + INTERVAL '7 days' 
                                      AND expiry_date > CURRENT_DATE THEN quantity ELSE 0 END), 0) as expiring_soon,
                    COALESCE(SUM(CASE WHEN expiry_date <= CURRENT_DATE THEN quantity ELSE 0 END), 0) as expired_units
                FROM blood_inventory bi
                WHERE bi.blood_bank_id IN (SELECT id FROM facility_blood_banks)
            ),
            request_stats AS (
                SELECT 
                    COALESCE(COUNT(*), 0) as total_requests,
                    COALESCE(SUM(CASE WHEN processing_status = 'completed' THEN quantity_requested ELSE 0 END), 0) as total_transferred
                FROM blood_requests br
                WHERE br.facility_id = :facility_id
                AND br.created_at::date BETWEEN :start_date AND :end_date
            )
            SELECT 
                i.total_stock,
                i.low_stock_items,
                i.expiring_soon,
                i.expired_units,
                r.total_requests,
                r.total_transferred
            FROM inventory_stats i
            CROSS JOIN request_stats r
        """)
        
        result = await self.db.execute(
            query,
            {
                'facility_id': str(facility_id),
                'start_date': date_range.start_date,
                'end_date': date_range.end_date
            }
        )
        
        row = result.fetchone()
        if not row:
            return {
                'total_stock': 0,
                'low_stock_items': 0,
                'expiring_soon': 0,
                'expired_units': 0,
                'total_requests': 0,
                'total_transferred': 0
            }
        
        return {
            'total_stock': row[0] or 0,
            'low_stock_items': row[1] or 0,
            'expiring_soon': row[2] or 0,
            'expired_units': row[3] or 0,
            'total_requests': row[4] or 0,
            'total_transferred': row[5] or 0
        }
    
    async def _get_blood_type_breakdown(self, facility_id: UUID) -> List[BloodTypeStats]:
        """Get breakdown by blood type"""
        
        query = text("""
            WITH facility_blood_banks AS (
                SELECT id FROM blood_banks WHERE facility_id = :facility_id
            )
            SELECT 
                bi.blood_type,
                COALESCE(SUM(bi.quantity), 0) as current_stock,
                COALESCE(COUNT(br.id), 0) as total_requests,
                COALESCE(SUM(CASE WHEN br.processing_status = 'completed' THEN br.quantity_requested ELSE 0 END), 0) as total_transferred,
                COALESCE(SUM(CASE WHEN bi.expiry_date <= CURRENT_DATE + INTERVAL '7 days' 
                                  AND bi.expiry_date > CURRENT_DATE THEN bi.quantity ELSE 0 END), 0) as expiring_soon,
                COALESCE(SUM(CASE WHEN bi.expiry_date <= CURRENT_DATE THEN bi.quantity ELSE 0 END), 0) as expired
            FROM blood_inventory bi
            LEFT JOIN blood_requests br ON bi.blood_type = br.blood_type AND br.facility_id = :facility_id
            WHERE bi.blood_bank_id IN (SELECT id FROM facility_blood_banks)
            GROUP BY bi.blood_type
            ORDER BY current_stock DESC
        """)
        
        result = await self.db.execute(query, {'facility_id': str(facility_id)})
        
        return [
            BloodTypeStats(
                blood_type=row[0],
                current_stock=row[1],
                total_requests=row[2],
                total_transferred=row[3],
                expiring_soon=row[4],
                expired=row[5]
            )
            for row in result.fetchall()
        ]
    
    async def _get_blood_product_breakdown(self, facility_id: UUID) -> List[BloodProductStats]:
        """Get breakdown by blood product"""
        
        query = text("""
            WITH facility_blood_banks AS (
                SELECT id FROM blood_banks WHERE facility_id = :facility_id
            )
            SELECT 
                bi.blood_product,
                COALESCE(SUM(bi.quantity), 0) as current_stock,
                COALESCE(COUNT(br.id), 0) as total_requests,
                COALESCE(SUM(CASE WHEN br.processing_status = 'completed' THEN br.quantity_requested ELSE 0 END), 0) as total_transferred,
                COALESCE(SUM(CASE WHEN bi.expiry_date <= CURRENT_DATE + INTERVAL '7 days' 
                                  AND bi.expiry_date > CURRENT_DATE THEN bi.quantity ELSE 0 END), 0) as expiring_soon
            FROM blood_inventory bi
            LEFT JOIN blood_requests br ON bi.blood_product = br.blood_product AND br.facility_id = :facility_id
            WHERE bi.blood_bank_id IN (SELECT id FROM facility_blood_banks)
            GROUP BY bi.blood_product
            ORDER BY current_stock DESC
        """)
        
        result = await self.db.execute(query, {'facility_id': str(facility_id)})
        
        return [
            BloodProductStats(
                blood_product=row[0],
                current_stock=row[1],
                total_requests=row[2],
                total_transferred=row[3],
                expiring_soon=row[4]
            )
            for row in result.fetchall()
        ]
    
    def _calculate_trend(self, current: int, previous: int) -> TrendData:
        """Calculate trend data between two periods"""
        if previous == 0:
            percentage_change = 100.0 if current > 0 else 0.0
        else:
            percentage_change = ((current - previous) / previous) * 100
        
        return TrendData(
            current_value=current,
            previous_value=previous,
            percentage_change=percentage_change,
            is_increase=current > previous
        )
    
    async def _get_system_inventory_stats(self, timeframe: StatsTimeframe) -> InventoryStatsResponse:
        """Get system-wide inventory statistics"""
        # This would aggregate across all facilities
        # Implementation similar to get_facility_stats but without facility filtering
        pass
    
    async def _get_total_facilities(self) -> int:
        """Get total number of facilities"""
        result = await self.db.execute(select(func.count(Facility.id)))
        return result.scalar() or 0
    
    async def _get_total_blood_banks(self) -> int:
        """Get total number of blood banks"""
        result = await self.db.execute(select(func.count(BloodBank.id)))
        return result.scalar() or 0
    
    async def _get_inter_facility_transfers(self) -> int:
        """Get number of inter-facility transfers"""
        # Count requests where requester facility != target facility
        query = text("""
            SELECT COUNT(*)
            FROM blood_requests br
            JOIN users u ON br.requester_id = u.id
            WHERE (u.facility_id IS NOT NULL AND u.facility_id != br.facility_id)
               OR (u.work_facility_id IS NOT NULL AND u.work_facility_id != br.facility_id)
        """)
        
        result = await self.db.execute(query)
        return result.scalar() or 0
    
    async def _calculate_network_efficiency(self) -> float:
        """Calculate network efficiency score"""
        # Placeholder for network efficiency calculation
        # This could be based on success rate, response time, etc.
        return 85.5  # Example value
    
    async def get_blood_bank_stats(self, blood_bank_id: UUID) -> Dict[str, Any]:
        """Get statistics for a specific blood bank"""
        
        query = text("""
            SELECT 
                COUNT(*) as total_inventory_items,
                COALESCE(SUM(quantity), 0) as total_units,
                COALESCE(SUM(CASE WHEN quantity < 10 THEN 1 ELSE 0 END), 0) as low_stock_items,
                COALESCE(SUM(CASE WHEN expiry_date <= CURRENT_DATE + INTERVAL '7 days' 
                                  AND expiry_date > CURRENT_DATE THEN quantity ELSE 0 END), 0) as expiring_soon,
                COALESCE(SUM(CASE WHEN expiry_date <= CURRENT_DATE THEN quantity ELSE 0 END), 0) as expired_units
            FROM blood_inventory
            WHERE blood_bank_id = :blood_bank_id
        """)
        
        result = await self.db.execute(query, {'blood_bank_id': str(blood_bank_id)})
        row = result.fetchone()
        
        if not row:
            return {
                'total_inventory_items': 0,
                'total_units': 0,
                'low_stock_items': 0,
                'expiring_soon': 0,
                'expired_units': 0
            }
        
        return {
            'total_inventory_items': row[0],
            'total_units': row[1],
            'low_stock_items': row[2],
            'expiring_soon': row[3],
            'expired_units': row[4]
        }