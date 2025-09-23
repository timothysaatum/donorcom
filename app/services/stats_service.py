from sqlalchemy import select, func, extract, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional
from app.models.request import (
    BloodRequest,
    DashboardDailySummary,
)
from app.models.distribution import BloodDistribution
import calendar
import uuid
from sqlalchemy.exc import SQLAlchemyError
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class StatsService:
    """Class-based service for handling all statistics-related operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def calculate_change(today_value: int, yesterday_value: int) -> tuple[float, str]:
        """Calculate percentage change and direction between two values."""
        if yesterday_value == 0:
            return 100.0 if today_value > 0 else 0.0, (
                "up" if today_value > 0 else "neutral"
            )

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
        yesterday_summary = (
            await self.db.execute(yesterday_query)
        ).scalar_one_or_none()

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
        stock_change, stock_dir = self.calculate_change(
            today_summary.total_stock, y_stock
        )
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
        blood_product_types: Optional[List[str]] = None,
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
            extract("month", BloodDistribution.date_delivered).label("month"),
            func.coalesce(func.sum(BloodDistribution.quantity), 0).label("total_units"),
        ).where(
            and_(
                BloodDistribution.dispatched_to_id == facility_id,
                BloodDistribution.date_delivered.is_not(None),
                extract("year", BloodDistribution.date_delivered) == year,
                BloodDistribution.status != "RETURNED",  # Exclude returned blood
            )
        )

        # Add blood product type filter if provided
        if blood_product_types:
            query = query.where(
                BloodDistribution.blood_product.in_(blood_product_types)
            )

        # Group by month and order by month
        query = query.group_by(extract("month", BloodDistribution.date_delivered))
        query = query.order_by(extract("month", BloodDistribution.date_delivered))

        result = await self.db.execute(query)
        monthly_data = result.fetchall()

        # Create a complete 12-month dataset with zero values for missing months
        monthly_stats = []
        data_dict = {row.month: row.total_units for row in monthly_data}

        for month_num in range(1, 13):
            month_name = calendar.month_name[month_num]
            monthly_stats.append(
                {
                    "month": month_name,
                    "month_number": month_num,
                    "total_units": data_dict.get(month_num, 0),
                    "year": year,
                }
            )

        return monthly_stats

    async def get_blood_product_breakdown(
        self,
        facility_id: uuid.UUID,
        year: Optional[int] = None,
        month: Optional[int] = None,
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
            func.coalesce(func.sum(BloodDistribution.quantity), 0).label("total_units"),
            func.count(BloodDistribution.id).label("total_transfers"),
        ).where(
            and_(
                BloodDistribution.dispatched_to_id == facility_id,
                BloodDistribution.date_delivered.is_not(None),
                extract("year", BloodDistribution.date_delivered) == year,
                BloodDistribution.status != "RETURNED",
            )
        )

        # Add month filter if provided
        if month:
            query = query.where(
                extract("month", BloodDistribution.date_delivered) == month
            )

        query = query.group_by(BloodDistribution.blood_product)
        query = query.order_by(BloodDistribution.blood_product)

        result = await self.db.execute(query)
        breakdown_data = result.fetchall()

        return [
            {
                "blood_product": row.blood_product,
                "total_units": row.total_units,
                "total_transfers": row.total_transfers,
            }
            for row in breakdown_data
        ]

    async def get_transfer_trends(
        self, facility_id: uuid.UUID, days: int = 30
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

        query = (
            select(
                func.date(BloodDistribution.date_delivered).label("transfer_date"),
                func.coalesce(func.sum(BloodDistribution.quantity), 0).label(
                    "total_units"
                ),
                func.count(BloodDistribution.id).label("total_transfers"),
            )
            .where(
                and_(
                    BloodDistribution.dispatched_to_id == facility_id,
                    BloodDistribution.date_delivered.is_not(None),
                    func.date(BloodDistribution.date_delivered) >= start_date,
                    BloodDistribution.status != "RETURNED",
                )
            )
            .group_by(func.date(BloodDistribution.date_delivered))
            .order_by(func.date(BloodDistribution.date_delivered))
        )

        result = await self.db.execute(query)
        trends_data = result.fetchall()

        return [
            {
                "date": row.transfer_date.isoformat(),
                "total_units": row.total_units,
                "total_transfers": row.total_transfers,
            }
            for row in trends_data
        ]

    async def get_distribution_chart_data(
        self,
        blood_bank_id: uuid.UUID,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        selected_blood_products: Optional[List] = None,
        selected_blood_types: Optional[List] = None,
    ) -> List[Dict[str, Any]]:
        # TODO: Add caching to improve speed and performance
        """
        Get blood distribution data for chart visualization.

        Returns daily distribution amounts (not cumulative) for the specified date range.
        """
        start_time = datetime.now()

        try:
            # Input validation
            if not blood_bank_id:
                raise ValueError("blood_bank_id is required")

            # Set default date range with reasonable limits
            if to_date is None:
                to_date = datetime.now().replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            if from_date is None:
                from_date = to_date - timedelta(days=7)
                from_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)

            # Validate date range
            if from_date >= to_date:
                raise ValueError("from_date must be before to_date")

            date_diff = (to_date - from_date).days
            if date_diff > 365:  # Limit to 1 year
                raise ValueError("Date range cannot exceed 365 days")

            # Process blood products with validation
            selected_blood_products_keys = await self._process_blood_products(
                selected_blood_products
            )
            selected_blood_types_values = await self._process_blood_types(
                selected_blood_types
            )

            # Get database product names efficiently
            db_product_names = self._get_db_product_names(selected_blood_products_keys)

            # Build and execute query
            query_conditions = self._build_query_conditions(
                blood_bank_id,
                from_date,
                to_date,
                db_product_names,
                selected_blood_types_values,
            )

            raw_data = await self._execute_distribution_query(query_conditions)

            # Process results efficiently
            chart_data = self._build_chart_data(
                raw_data, from_date, to_date, selected_blood_products_keys
            )

            # Log performance metrics
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.info(
                f"Distribution chart data generated: {len(chart_data)} points, "
                f"{len(raw_data)} raw records, {execution_time:.3f}s"
            )

            return chart_data

        except SQLAlchemyError as e:
            logger.error(f"Database error in get_distribution_chart_data: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_distribution_chart_data: {str(e)}")
            raise

    async def _process_blood_products(
        self, selected_blood_products: Optional[List]
    ) -> List[str]:
        """Process and validate blood product selections."""
        if selected_blood_products is None:
            return ["whole_blood", "red_blood_cells", "platelets"]

        # Define valid mappings once
        enum_to_key = {
            "Whole Blood": "whole_blood",
            "Red Blood Cells": "red_blood_cells",
            "Red Cells": "red_blood_cells",
            "Platelets": "platelets",
            "Fresh Frozen Plasma": "fresh_frozen_plasma",
            "Plasma": "fresh_frozen_plasma",
            "Cryoprecipitate": "cryoprecipitate",
            "Albumin": "albumin",
        }

        valid_keys = set(enum_to_key.values())
        selected_keys = []

        for product in selected_blood_products:
            if hasattr(product, "value"):  # Enum
                api_key = enum_to_key.get(product.value)
                if not api_key:
                    logger.warning(f"Unknown blood product enum: {product.value}")
                    continue
                selected_keys.append(api_key)
            else:  # String
                if product not in valid_keys:
                    logger.warning(f"Invalid blood product key: {product}")
                    continue
                selected_keys.append(product)

        if not selected_keys:
            raise ValueError("No valid blood products selected")

        return list(set(selected_keys))  # Remove duplicates

    async def _process_blood_types(
        self, selected_blood_types: Optional[List]
    ) -> Optional[List[str]]:
        """Process and validate blood type selections."""
        if not selected_blood_types:
            return None

        blood_types = []
        for bt in selected_blood_types:
            if hasattr(bt, "value"):
                blood_types.append(bt.value)
            else:
                blood_types.append(bt)

        return blood_types

    def _get_db_product_names(self, selected_keys: List[str]) -> List[str]:
        """Map API keys to database product names efficiently."""
        key_to_db_mapping = {
            "whole_blood": ["Whole Blood"],
            "red_blood_cells": ["Red Blood Cells", "Red Cells"],
            "platelets": ["Platelets"],
            "fresh_frozen_plasma": ["Fresh Frozen Plasma", "Plasma"],
            "cryoprecipitate": ["Cryoprecipitate"],
            "albumin": ["Albumin"],
        }

        db_names = []
        for key in selected_keys:
            if key in key_to_db_mapping:
                db_names.extend(key_to_db_mapping[key])

        return db_names

    def _build_query_conditions(
        self,
        blood_bank_id: uuid.UUID,
        from_date: datetime,
        to_date: datetime,
        db_product_names: List[str],
        blood_types: Optional[List[str]],
    ) -> List:
        """Build query conditions with proper indexing considerations."""
        conditions = [
            BloodDistribution.dispatched_from_id == blood_bank_id,  # Primary filter
            BloodDistribution.date_delivered.is_not(None),
            BloodDistribution.date_delivered >= from_date,
            BloodDistribution.date_delivered <= to_date,
            BloodDistribution.status.in_(["DELIVERED", "DISPATCHED"]),
        ]

        if db_product_names:
            conditions.append(BloodDistribution.blood_product.in_(db_product_names))

        if blood_types:
            conditions.append(BloodDistribution.blood_type.in_(blood_types))

        return conditions

    async def _execute_distribution_query(self, query_conditions: List) -> List:
        """Execute the distribution query with error handling."""
        query = (
            select(
                func.date(BloodDistribution.date_delivered).label("distribution_date"),
                BloodDistribution.blood_product,
                BloodDistribution.blood_type,
                func.sum(BloodDistribution.quantity).label("daily_received"),
            )
            .where(and_(*query_conditions))
            .group_by(
                func.date(BloodDistribution.date_delivered),
                BloodDistribution.blood_product,
                BloodDistribution.blood_type,
            )
            .order_by(func.date(BloodDistribution.date_delivered))
        )

        result = await self.db.execute(query)
        return result.fetchall()

    def _build_chart_data(
        self,
        raw_data: List,
        from_date: datetime,
        to_date: datetime,
        selected_keys: List[str],
    ) -> List[Dict[str, Any]]:
        """Build chart data more efficiently without unnecessary loops."""

        # Create reverse mapping once
        db_to_key_mapping = {
            "Whole Blood": "whole_blood",
            "Red Blood Cells": "red_blood_cells",
            "Red Cells": "red_blood_cells",
            "Platelets": "platelets",
            "Fresh Frozen Plasma": "fresh_frozen_plasma",
            "Plasma": "fresh_frozen_plasma",
            "Cryoprecipitate": "cryoprecipitate",
            "Albumin": "albumin",
        }

        # Group data by date efficiently
        data_by_date = {}
        for row in raw_data:
            date_key = row.distribution_date
            api_key = db_to_key_mapping.get(row.blood_product)

            if api_key and api_key in selected_keys:
                if date_key not in data_by_date:
                    data_by_date[date_key] = {}

                data_by_date[date_key][api_key] = (
                    data_by_date[date_key].get(api_key, 0) + row.daily_received
                )

        # Generate chart data - only for dates that have data or are explicitly needed
        chart_data = []
        current_date = from_date.date()
        end_date = to_date.date()

        # If we have sparse data, we might want to include zero days
        # For performance, you could skip days with no data:
        # for date_str in sorted(data_by_date.keys()):

        while current_date <= end_date:
            date_key = current_date.isoformat()

            chart_point = {
                "date": current_date.isoformat() + "T10:30:00Z",
                "formattedDate": current_date.strftime("%b %d"),
            }

            # Add data for selected products (0 if no data for that date)
            day_data = data_by_date.get(date_key, {})
            for api_key in selected_keys:
                chart_point[api_key] = day_data.get(api_key, 0)

            chart_data.append(chart_point)
            current_date += timedelta(days=1)

        return chart_data


class RequestTrackingService:
    """Service for handling blood request tracking and analytics."""

    def __init__(self, db):
        self.db = db

    async def get_request_chart_data(
        self,
        facility_id: uuid.UUID,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        selected_blood_products: Optional[List] = None,
        selected_blood_types: Optional[List] = None,
        request_direction: Optional[str] = None,  # "sent", "received", or None for both
    ) -> List[Dict[str, Any]]:
        """
        Get blood request data for chart visualization.

        Returns daily request amounts (not cumulative) for the specified date range.
        Supports filtering by sent/received requests.
        """
        start_time = datetime.now()

        try:
            # Input validation
            if not facility_id:
                raise ValueError("facility_id is required")

            # Set default date range with reasonable limits
            if to_date is None:
                to_date = datetime.now().replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            if from_date is None:
                from_date = to_date - timedelta(days=7)
                from_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)

            # Validate date range
            if from_date >= to_date:
                raise ValueError("from_date must be before to_date")

            date_diff = (to_date - from_date).days
            if date_diff > 365:  # Limit to 1 year
                raise ValueError("Date range cannot exceed 365 days")

            # Process filters with validation
            selected_blood_products_keys = await self._process_blood_products(
                selected_blood_products
            )
            selected_blood_types_values = await self._process_blood_types(
                selected_blood_types
            )

            # Get database product names efficiently
            db_product_names = self._get_db_product_names(selected_blood_products_keys)

            # Build and execute query
            query_conditions = self._build_query_conditions(
                facility_id,
                from_date,
                to_date,
                db_product_names,
                selected_blood_types_values,
                request_direction,
            )

            raw_data = await self._execute_request_query(query_conditions)

            # Process results efficiently
            chart_data = self._build_chart_data(
                raw_data, from_date, to_date, selected_blood_products_keys
            )

            # Log performance metrics
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.info(
                f"Request chart data generated: {len(chart_data)} points, "
                f"{len(raw_data)} raw records, {execution_time:.3f}s, direction: {request_direction}"
            )

            return chart_data

        except SQLAlchemyError as e:
            logger.error(f"Database error in get_request_chart_data: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_request_chart_data: {str(e)}")
            raise

    async def _process_blood_products(
        self, selected_blood_products: Optional[List]
    ) -> List[str]:
        """Process and validate blood product selections."""
        if selected_blood_products is None or len(selected_blood_products) == 0:
            return ["whole_blood", "red_blood_cells", "platelets"]

        # mapping to match your inventory schema
        enum_to_key = {
            "Whole Blood": "whole_blood",
            "Red Blood Cells": "red_blood_cells",  # This matches your request data
            "Red Cells": "red_blood_cells",  # Alternative name
            "Platelets": "platelets",
            "Fresh Frozen Plasma": "fresh_frozen_plasma",
            "Plasma": "fresh_frozen_plasma",  # Alternative name
            "Cryoprecipitate": "cryoprecipitate",
            "Albumin": "albumin",
        }
        valid_keys = set(enum_to_key.values())
        selected_keys = []

        for product in selected_blood_products:
            if hasattr(product, "value"):  # Enum
                api_key = enum_to_key.get(product.value)
                if not api_key:
                    logger.warning(f"Unknown blood product enum: {product.value}")
                    continue
                selected_keys.append(api_key)
            else:  # String
                # Handle both API key format and database format
                product_str = str(product).strip()
                if product_str in valid_keys:
                    # Direct API key match (e.g., "red_blood_cells")
                    selected_keys.append(product_str)
                elif product_str in enum_to_key:
                    # Database format match (e.g., "Red Blood Cells")
                    selected_keys.append(enum_to_key[product_str])
                else:
                    logger.warning(f"Invalid blood product key: {product_str}")
                    continue

        if not selected_keys:
            logger.warning("No valid blood products after processing, using defaults")
            return ["whole_blood", "red_blood_cells", "platelets"]
        return list(set(selected_keys))  # Remove duplicates

    async def _process_blood_types(
        self, selected_blood_types: Optional[List]
    ) -> Optional[List[str]]:
        """Process and validate blood type selections."""
        if not selected_blood_types:
            return None

        blood_types = []
        for bt in selected_blood_types:
            if hasattr(bt, "value"):
                blood_types.append(bt.value)
            else:
                blood_types.append(bt)
        return blood_types

    def _get_db_product_names(self, selected_keys: List[str]) -> List[str]:
        """Map API keys to database product names efficiently."""
        # FIXED: Updated mapping to match your actual database values
        key_to_db_mapping = {
            "whole_blood": ["Whole Blood"],
            "red_blood_cells": [
                "Red Blood Cells",
                "Red Cells",
            ],  # Include both variants
            "platelets": ["Platelets"],
            "fresh_frozen_plasma": ["Fresh Frozen Plasma", "Plasma"],
            "cryoprecipitate": ["Cryoprecipitate"],
            "albumin": ["Albumin"],
        }

        db_names = []
        for key in selected_keys:
            if key in key_to_db_mapping:
                db_names.extend(key_to_db_mapping[key])
            else:
                logger.warning(f"No database mapping found for API key: {key}")

        logger.info(f"Mapped API keys {selected_keys} to DB names {db_names}")
        return db_names

    def _build_query_conditions(
        self,
        facility_id: uuid.UUID,
        from_date: datetime,
        to_date: datetime,
        db_product_names: List[str],
        blood_types: Optional[List[str]],
        request_direction: Optional[str],
    ) -> List:
        """Build query conditions with proper indexing considerations."""
        conditions = [
            BloodRequest.created_at >= from_date,
            BloodRequest.created_at <= to_date,
        ]

        # Handle sent vs received requests using the new explicit facility relationships
        if request_direction == "sent":
            # Sent requests: requests originating from this facility (source_facility_id)
            conditions.append(BloodRequest.source_facility_id == facility_id)
        elif request_direction == "received":
            # Received requests: requests sent TO this facility (facility_id = target facility)
            conditions.append(BloodRequest.facility_id == facility_id)
        else:
            # Both sent and received
            conditions.append(
                or_(
                    BloodRequest.source_facility_id
                    == facility_id,  # Sent by this facility
                    BloodRequest.facility_id
                    == facility_id,  # Received by this facility
                )
            )

        if db_product_names:
            conditions.append(BloodRequest.blood_product.in_(db_product_names))

        if blood_types:
            conditions.append(BloodRequest.blood_type.in_(blood_types))
        return conditions

    async def _execute_request_query(self, query_conditions: List) -> List:
        """Execute the request query with error handling."""
        query = (
            select(
                func.date(BloodRequest.created_at).label("request_date"),
                BloodRequest.blood_product,
                BloodRequest.blood_type,
                func.sum(BloodRequest.quantity_requested).label("daily_requested"),
            )
            .where(and_(*query_conditions))
            .group_by(
                func.date(BloodRequest.created_at),
                BloodRequest.blood_product,
                BloodRequest.blood_type,
            )
            .order_by(func.date(BloodRequest.created_at))
        )

        result = await self.db.execute(query)
        raw_data = result.fetchall()
        return raw_data

    def _build_chart_data(
        self,
        raw_data: List,
        from_date: datetime,
        to_date: datetime,
        selected_keys: List[str],
    ) -> List[Dict[str, Any]]:
        """Build chart data with proper null handling for unselected products."""

        db_to_key_mapping = {
            "Whole Blood": "whole_blood",
            "Red Blood Cells": "red_blood_cells",
            "Platelets": "platelets",
            "Fresh Frozen Plasma": "fresh_frozen_plasma",
            "Plasma": "fresh_frozen_plasma",
            "Cryoprecipitate": "cryoprecipitate",
            "Albumin": "albumin",
        }

        # All possible product keys
        all_product_keys = [
            "whole_blood",
            "red_blood_cells",
            "platelets",
            "fresh_frozen_plasma",
            "cryoprecipitate",
            "albumin",
        ]

        logger.info(f"Processing raw data with {len(raw_data)} records")
        logger.info(f"Selected keys: {selected_keys}")
        logger.info(f"DB to key mapping: {db_to_key_mapping}")

        # Group data by date efficiently
        data_by_date = {}
        for row in raw_data:
            date_key = (
                row.request_date.isoformat()
                if hasattr(row.request_date, "isoformat")
                else str(row.request_date)
            )
            api_key = db_to_key_mapping.get(row.blood_product)

            logger.info(
                f"Processing: Date={date_key}, Product='{row.blood_product}' -> API_Key='{api_key}', Quantity={row.daily_requested}"
            )

            if api_key and api_key in selected_keys:
                if date_key not in data_by_date:
                    data_by_date[date_key] = {}

                data_by_date[date_key][api_key] = (
                    data_by_date[date_key].get(api_key, 0) + row.daily_requested
                )
                logger.info(
                    f"Added {row.daily_requested} to {api_key} for {date_key}. Total: {data_by_date[date_key][api_key]}"
                )
            else:
                logger.warning(
                    f"Skipping: Product '{row.blood_product}' -> API_Key '{api_key}', in_selected: {api_key in selected_keys if api_key else False}"
                )

        logger.info(f"Final data_by_date: {data_by_date}")

        # Generate chart data
        chart_data = []
        current_date = from_date.date()
        end_date = to_date.date()

        while current_date <= end_date:
            date_key = current_date.isoformat()

            chart_point = {
                "date": current_date.isoformat() + "T10:30:00Z",
                "formattedDate": current_date.strftime("%b %d"),
            }

            # Add data for ALL products, but:
            # - Selected products get actual values (0 if no data for that date)
            # - Unselected products get null
            day_data = data_by_date.get(date_key, {})
            for api_key in all_product_keys:
                if api_key in selected_keys:
                    # Selected product: use actual value or 0
                    chart_point[api_key] = day_data.get(api_key, 0)
                else:
                    # Unselected product: set to null
                    chart_point[api_key] = None

            chart_data.append(chart_point)
            current_date += timedelta(days=1)

        logger.info(f"Generated {len(chart_data)} chart data points")
        return chart_data
