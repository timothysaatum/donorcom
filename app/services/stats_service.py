from sqlalchemy import select, func, extract, and_, case, or_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime, timedelta
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

    async def get_inventory_chart_data(
        self,
        facility_id: uuid.UUID,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        selected_blood_products: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get blood product inventory data for chart visualization.
        Now supports filtering by selected blood products.

        Args:
            facility_id: The facility ID to get data for
            from_date: Start date for data filtering (defaults to 7 days ago)
            to_date: End date for data filtering (defaults to today)
            selected_blood_products: List of blood product types to include in response

        Returns:
            List of daily inventory data points for chart rendering
        """
        # Set default date range if not provided
        if to_date is None:
                to_date = datetime.now().replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
        if from_date is None:
            from_date = to_date - timedelta(days=7)
            from_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)

        # Set default blood products if not provided
        if selected_blood_products is None:
            selected_blood_products = [
                "whole_blood",
                "red_blood_cells", 
                "platelets",
                "fresh_frozen_plasma",
                "cryoprecipitate",
                "albumin",
            ]

        # Map your blood product names to the expected keys
        product_mapping = {
            "Whole Blood": "whole_blood",
            "Red Blood Cells": "red_blood_cells",
            "Red Cells": "red_blood_cells", 
            "Platelets": "platelets",
            "Fresh Frozen Plasma": "fresh_frozen_plasma",
            "Plasma": "fresh_frozen_plasma",
            "Cryoprecipitate": "cryoprecipitate",
            "Albumin": "albumin",
        }

        # Reverse mapping for database queries (get DB names from API keys)
        reverse_mapping = {}
        for db_name, api_key in product_mapping.items():
            if api_key not in reverse_mapping:
                reverse_mapping[api_key] = []
        reverse_mapping[api_key].append(db_name)

        # Get database product names for selected products only
        db_product_names = []
        for selected_product in selected_blood_products:
            if selected_product in reverse_mapping:
                db_product_names.extend(reverse_mapping[selected_product])

        # Query to get inventory movements (both in and out) - FILTERED by selected products
        query = (
            select(
                func.date(BloodDistribution.date_delivered).label("inventory_date"),
                BloodDistribution.blood_product,
            func.sum(
                case(
                    (
                        BloodDistribution.dispatched_to_id == facility_id,
                        BloodDistribution.quantity,
                    ),
                    else_=0,
                )
            ).label("received"),
            func.sum(
                case(
                    (
                        BloodDistribution.dispatched_from_id == facility_id,
                        BloodDistribution.quantity,
                    ),
                    else_=0,
                )
            ).label("dispatched"),
        )
        .where(
            and_(
                or_(
                    BloodDistribution.dispatched_to_id == facility_id,
                    BloodDistribution.dispatched_from_id == facility_id,
                ),
                BloodDistribution.date_delivered.is_not(None),
                BloodDistribution.date_delivered >= from_date,
                BloodDistribution.date_delivered <= to_date,
                BloodDistribution.status.in_(["delivered", "dispatched"]),
                # NEW: Filter by selected blood products only
                BloodDistribution.blood_product.in_(db_product_names) if db_product_names else True,
            )
        )
        .group_by(
            func.date(BloodDistribution.date_delivered),
            BloodDistribution.blood_product,
        )
        .order_by(func.date(BloodDistribution.date_delivered))
    )

        result = await self.db.execute(query)
    
        raw_data = result.fetchall()

        # Get initial inventory levels for ALL products (even if not selected, for consistency)
        all_running_totals = await self._get_current_inventory_levels(facility_id)
    
        # Initialize running totals only for selected products
        running_totals = {
            product: all_running_totals.get(product, 0) 
            for product in selected_blood_products
        }

        # Group data by date
        data_by_date = {}
        for row in raw_data:
            date_key = row.inventory_date.isoformat()
            if date_key not in data_by_date:
                data_by_date[date_key] = {}

            product_key = product_mapping.get(row.blood_product)
            if product_key and product_key in selected_blood_products:  # Only process selected products
                # Net change = received - dispatched
                net_change = (row.received or 0) - (row.dispatched or 0)
                data_by_date[date_key][product_key] = net_change

        # Generate chart data with running totals for selected products only
        chart_data = []
        current_date = from_date.date()
        end_date = to_date.date()

        while current_date <= end_date:
            date_key = current_date.isoformat()

        # Apply any changes for this date
        if date_key in data_by_date:
            for product_key, change in data_by_date[date_key].items():
                if product_key in running_totals:  # Only update selected products
                    running_totals[product_key] += change

        # Create chart data point with ONLY selected products
        chart_point = {
            "date": current_date.isoformat() + "T10:30:00Z",
            "formattedDate": current_date.strftime("%b %d"),
        }
        
        # Add only the selected blood products to the response
        for product_key in selected_blood_products:
            chart_point[product_key] = max(0, running_totals.get(product_key, 0))

        chart_data.append(chart_point)
        current_date += timedelta(days=1)

        return chart_data
