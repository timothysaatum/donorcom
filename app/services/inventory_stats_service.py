from datetime import date, timedelta
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, and_, select, or_
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest, ProcessingStatus, DashboardDailySummary
from app.models.health_facility import Facility
from app.models.user import User
from app.models.blood_bank import BloodBank
import logging
import uuid


logger = logging.getLogger(__name__)

router = APIRouter()


class DashboardStatsService:
    """Service class for dashboard statistics calculations"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_facility_stats(self, user: User, target_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Get comprehensive dashboard stats for a user's facility
        """
        if target_date is None:
            target_date = date.today()
        
        previous_date = target_date - timedelta(days=1)
        
        # Get the user's facility (either managed or work facility)
        facility_id = await self._get_user_facility_id(user)
        
        if not facility_id:
            raise HTTPException(
                status_code=400,
                detail="User is not associated with any facility"
            )
        
        # Get current stats
        current_stats = await self._get_daily_stats(facility_id, target_date)
        previous_stats = await self._get_daily_stats(facility_id, previous_date)
        
        # Calculate percentage changes
        stock_change = self._calculate_percentage_change(
            previous_stats['total_stock'], 
            current_stats['total_stock']
        )
        
        transferred_change = self._calculate_percentage_change(
            previous_stats['total_transferred'], 
            current_stats['total_transferred']
        )
        
        requests_change = self._calculate_percentage_change(
            previous_stats['total_requests'], 
            current_stats['total_requests']
        )
        
        return {
            "total_blood_in_stock": {
                "value": current_stats['total_stock'],
                "unit": "Units",
                "change_percentage": stock_change['percentage'],
                "change_direction": stock_change['direction'],
                "change_text": f"{'Up' if stock_change['direction'] == 'up' else 'Down'} from yesterday"
            },
            "total_transferred": {
                "value": current_stats['total_transferred'],
                "unit": "Units", 
                "change_percentage": transferred_change['percentage'],
                "change_direction": transferred_change['direction'],
                "change_text": f"{'Up' if transferred_change['direction'] == 'up' else 'Down'} from yesterday"
            },
            "total_requests": {
                "value": current_stats['total_requests'],
                "unit": "Units",
                "change_percentage": requests_change['percentage'],
                "change_direction": requests_change['direction'],
                "change_text": f"{'Up' if requests_change['direction'] == 'up' else 'Down'} from yesterday"
            },
            "date": target_date.isoformat(),
            "previous_date": previous_date.isoformat(),
            "facility_id": str(facility_id)
        }
    
    async def _get_user_facility_id(self, user: User) -> Optional[uuid.UUID]:
        """
        Get the facility ID for a user based on their role and relationships
        """
        # For facility administrators - they manage a facility
        if user.role == 'facility_administrator':
            facility_query = select(Facility.id).where(Facility.facility_manager_id == user.id)
            result = await self.db.execute(facility_query)
            facility_id = result.scalar_one_or_none()
            return facility_id
        
        # For staff and lab_managers - they work at a facility
        elif user.role in ['staff', 'lab_manager']:
            return user.work_facility_id
        
        return None
    
    async def _get_daily_stats(self, facility_id: uuid.UUID, target_date: date) -> Dict[str, int]:
        """
        Get or calculate daily stats for a specific date
        Uses cached summary if available, otherwise calculates fresh
        """
        # Try to get from cache first
        cache_query = select(DashboardDailySummary).where(
            and_(
                DashboardDailySummary.facility_id == facility_id,
                DashboardDailySummary.date == target_date
            )
        )
        result = await self.db.execute(cache_query)
        cached_summary = result.scalar_one_or_none()
        
        if cached_summary and target_date < date.today():
            # Use cached data for historical dates
            return {
                'total_stock': cached_summary.total_stock,
                'total_transferred': cached_summary.total_transferred,
                'total_requests': cached_summary.total_requests
            }
        
        # Calculate fresh stats (for today or if no cache)
        return await self._calculate_fresh_stats(facility_id, target_date)
    
    async def _calculate_fresh_stats(self, facility_id: uuid.UUID, target_date: date) -> Dict[str, int]:
        """Calculate fresh statistics for the given date"""
        
        # Get the blood bank ID for this facility
        blood_bank_query = select(BloodBank.id).where(BloodBank.facility_id == facility_id)
        result = await self.db.execute(blood_bank_query)
        blood_bank_id = result.scalar_one_or_none()
        
        # Total blood in stock (current inventory)
        if blood_bank_id:
            stock_query = select(
                func.coalesce(func.sum(BloodInventory.quantity), 0)
            ).where(
                and_(
                    BloodInventory.blood_bank_id == blood_bank_id,
                    BloodInventory.expiry_date > target_date  # Only non-expired blood
                )
            )
            result = await self.db.execute(stock_query)
            total_stock = result.scalar() or 0
        else:
            total_stock = 0
        
        # Total transferred (completed requests fulfilled by users from this facility)
        # Get all user IDs from this facility
        facility_users_query = select(User.id).where(
            or_(
                User.work_facility_id == facility_id,  # Staff and lab managers
                and_(  # Facility administrators
                    User.role == 'facility_administrator',
                    User.id.in_(
                        select(Facility.facility_manager_id).where(Facility.id == facility_id)
                    )
                )
            )
        )
        result = await self.db.execute(facility_users_query)
        facility_user_ids = [row[0] for row in result.fetchall()]
        
        if facility_user_ids:
            transferred_query = select(
                func.coalesce(func.sum(BloodRequest.quantity_requested), 0)
            ).where(
                and_(
                    BloodRequest.fulfilled_by_id.in_(facility_user_ids),
                    BloodRequest.processing_status == ProcessingStatus.completed,
                    func.date(BloodRequest.updated_at) == target_date
                )
            )
            result = await self.db.execute(transferred_query)
            total_transferred = result.scalar() or 0
        else:
            total_transferred = 0
        
        # Total requests (all requests made by this facility)
        requests_query = select(
            func.coalesce(func.sum(BloodRequest.quantity_requested), 0)
        ).where(
            and_(
                BloodRequest.facility_id == facility_id,
                func.date(BloodRequest.created_at) == target_date
            )
        )
        result = await self.db.execute(requests_query)
        total_requests = result.scalar() or 0
        
        return {
            'total_stock': total_stock,
            'total_transferred': total_transferred, 
            'total_requests': total_requests
        }
    
    def _calculate_percentage_change(self, previous: int, current: int) -> Dict[str, Any]:
        """Calculate percentage change between two values"""
        if previous == 0:
            if current > 0:
                return {"percentage": 100, "direction": "up"}
            else:
                return {"percentage": 0, "direction": "neutral"}
        
        change = ((current - previous) / previous) * 100
        direction = "up" if change > 0 else "down" if change < 0 else "neutral"
        
        return {
            "percentage": abs(round(change, 1)),
            "direction": direction
        }
    
    async def update_daily_summary(self, facility_id: uuid.UUID, target_date: date) -> None:
        """
        Update or create daily summary cache
        This can be called by a background job
        """
        stats = await self._calculate_fresh_stats(facility_id, target_date)
        
        # Check if summary exists
        existing_query = select(DashboardDailySummary).where(
            and_(
                DashboardDailySummary.facility_id == facility_id,
                DashboardDailySummary.date == target_date
            )
        )
        result = await self.db.execute(existing_query)
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update existing
            existing.total_stock = stats['total_stock']
            existing.total_transferred = stats['total_transferred']
            existing.total_requests = stats['total_requests']
            existing.updated_at = func.now()
        else:
            # Create new
            new_summary = DashboardDailySummary(
                facility_id=facility_id,
                date=target_date,
                total_stock=stats['total_stock'],
                total_transferred=stats['total_transferred'],
                total_requests=stats['total_requests']
            )
            self.db.add(new_summary)
        
        await self.db.commit()