from sqlalchemy import select, func, extract, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, timedelta
from typing import List, Dict, Any, Optional
from app.models.request import DashboardDailySummary
from app.models.distribution import BloodDistribution
import calendar
import uuid


class StatsService:
    """Class-based service for handling all statistics-related operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    @staticmethod
    def calculate_change(today_value: int, yesterday_value: int) -> tuple[float, str]:
        """Calculate percentage change and direction between two values."""
        if yesterday_value == 0:
            return 100.0 if today_value > 0 else 0.0, "up" if today_value > 0 else "neutral"
        
        change = ((today_value - yesterday_value) / yesterday_value) * 100
        direction = "up" if change > 0 else "down" if change < 0 else "neutral"
        return round(change, 2), direction

    async def get_dashboard_summary(self, facility_id: uuid.UUID) -> Dict[str, Any]:
        """Get dashboard summary with today vs yesterday comparisons."""
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Today's summary
        today_query = select(DashboardDailySummary).where(
            and_(
                DashboardDailySummary.facility_id == facility_id,
                DashboardDailySummary.date == today,
            )
        )
        today_summary = (await self.db.execute(today_query)).scalar_one_or_none()

        # Yesterday's summary
        yesterday_query = select(DashboardDailySummary).where(
            and_(
                DashboardDailySummary.facility_id == facility_id,
                DashboardDailySummary.date == yesterday,
            )
        )
        yesterday_summary = (await self.db.execute(yesterday_query)).scalar_one_or_none()

        if not today_summary:
            return {
                "stock": {"value": 0, "change": 0.0, "direction": "neutral"},
                "transferred": {"value": 0, "change": 0.0, "direction": "neutral"},
                "requests": {"value": 0, "change": 0.0, "direction": "neutral"},
            }

        # Yesterday values (default to 0 if no data)
        y_stock = yesterday_summary.total_stock if yesterday_summary else 0
        y_transferred = yesterday_summary.total_transferred if yesterday_summary else 0
        y_requests = yesterday_summary.total_requests if yesterday_summary else 0

        # Calculate changes
        stock_change, stock_dir = self.calculate_change(today_summary.total_stock, y_stock)
        transferred_change, transferred_dir = self.calculate_change(
            today_summary.total_transferred, y_transferred
        )
        requests_change, requests_dir = self.calculate_change(
            today_summary.total_requests, y_requests
        )

        return {
            "stock": {
                "value": today_summary.total_stock,
                "change": stock_change,
                "direction": stock_dir,
            },
            "transferred": {
                "value": today_summary.total_transferred,
                "change": transferred_change,
                "direction": transferred_dir,
            },
            "requests": {
                "value": today_summary.total_requests,
                "change": requests_change,
                "direction": requests_dir,
            },
        }

    async def get_monthly_transfer_stats(
        self, 
        facility_id: uuid.UUID, 
        year: Optional[int] = None,
        blood_product_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get monthly blood transfer statistics for a facility.
        
        Args:
            facility_id: The facility ID to get stats for
            year: Year to get stats for (defaults to current year)
            blood_product_types: Optional list of blood product types to filter by
            
        Returns:
            List of monthly data with month names and transfer counts
        """
        if year is None:
            year = date.today().year

        # Base query for blood distributions delivered to the facility
        query = select(
            extract('month', BloodDistribution.date_delivered).label('month'),
            func.coalesce(func.sum(BloodDistribution.quantity), 0).label('total_units')
        ).where(
            and_(
                BloodDistribution.dispatched_to_id == facility_id,
                BloodDistribution.date_delivered.is_not(None),
                extract('year', BloodDistribution.date_delivered) == year,
                BloodDistribution.status != 'returned'  # Exclude returned blood
            )
        )
        
        # Add blood product type filter if provided
        if blood_product_types:
            query = query.where(BloodDistribution.blood_product.in_(blood_product_types))
        
        # Group by month and order by month
        query = query.group_by(extract('month', BloodDistribution.date_delivered))
        query = query.order_by(extract('month', BloodDistribution.date_delivered))

        result = await self.db.execute(query)
        monthly_data = result.fetchall()

        # Create a complete 12-month dataset with zero values for missing months
        monthly_stats = []
        data_dict = {row.month: row.total_units for row in monthly_data}
        
        for month_num in range(1, 13):
            month_name = calendar.month_name[month_num]
            monthly_stats.append({
                "month": month_name,
                "month_number": month_num,
                "total_units": data_dict.get(month_num, 0),
                "year": year
            })

        return monthly_stats

    async def get_blood_product_breakdown(
        self, 
        facility_id: uuid.UUID, 
        year: Optional[int] = None,
        month: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get breakdown of blood transfers by product type.
        
        Args:
            facility_id: The facility ID to get stats for
            year: Year to filter by (defaults to current year)
            month: Optional month to filter by
            
        Returns:
            List of blood product types with their transfer counts
        """
        if year is None:
            year = date.today().year

        query = select(
            BloodDistribution.blood_product,
            func.coalesce(func.sum(BloodDistribution.quantity), 0).label('total_units'),
            func.count(BloodDistribution.id).label('total_transfers')
        ).where(
            and_(
                BloodDistribution.dispatched_to_id == facility_id,
                BloodDistribution.date_delivered.is_not(None),
                extract('year', BloodDistribution.date_delivered) == year,
                BloodDistribution.status != 'returned'
            )
        )

        # Add month filter if provided
        if month:
            query = query.where(extract('month', BloodDistribution.date_delivered) == month)

        query = query.group_by(BloodDistribution.blood_product)
        query = query.order_by(BloodDistribution.blood_product)

        result = await self.db.execute(query)
        breakdown_data = result.fetchall()

        return [
            {
                "blood_product": row.blood_product,
                "total_units": row.total_units,
                "total_transfers": row.total_transfers
            }
            for row in breakdown_data
        ]

    async def get_transfer_trends(
        self, 
        facility_id: uuid.UUID, 
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Get daily transfer trends for the last N days.
        
        Args:
            facility_id: The facility ID to get stats for
            days: Number of days to look back (default 30)
            
        Returns:
            List of daily transfer data
        """
        start_date = date.today() - timedelta(days=days)
        
        query = select(
            func.date(BloodDistribution.date_delivered).label('transfer_date'),
            func.coalesce(func.sum(BloodDistribution.quantity), 0).label('total_units'),
            func.count(BloodDistribution.id).label('total_transfers')
        ).where(
            and_(
                BloodDistribution.dispatched_to_id == facility_id,
                BloodDistribution.date_delivered.is_not(None),
                func.date(BloodDistribution.date_delivered) >= start_date,
                BloodDistribution.status != 'returned'
            )
        ).group_by(
            func.date(BloodDistribution.date_delivered)
        ).order_by(
            func.date(BloodDistribution.date_delivered)
        )

        result = await self.db.execute(query)
        trends_data = result.fetchall()

        return [
            {
                "date": row.transfer_date.isoformat(),
                "total_units": row.total_units,
                "total_transfers": row.total_transfers
            }
            for row in trends_data
        ]