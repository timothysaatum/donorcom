from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional
from app.models.request import (
    BloodRequest,
    DashboardDailySummary,
)
from app.models.distribution import BloodDistribution
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
        selected_keys: List[str],  # This argument is not needed, but keep for compatibility
    ) -> List[Dict[str, Any]]:
        """Build chart data with human-readable blood product names as keys."""

        db_to_human = {
            "Whole Blood": "Whole Blood",
            "Red Blood Cells": "Red Blood Cells",
            "Red Cells": "Red Blood Cells",
            "Platelets": "Platelets",
            "Fresh Frozen Plasma": "Fresh Frozen Plasma",
            "Plasma": "Fresh Frozen Plasma",
            "Cryoprecipitate": "Cryoprecipitate",
            "Albumin": "Albumin",
        }
        canonical_products = [
            "Whole Blood",
            "Red Blood Cells",
            "Platelets",
            "Fresh Frozen Plasma",
            "Cryoprecipitate",
            "Albumin",
        ]
        # Only collect human-readable keys in data_by_date
        data_by_date = {}
        for row in raw_data:
            date_key = (
                getattr(row, "distribution_date", None)
                or getattr(row, "request_date", None)
                or (row[0] if isinstance(row, (list, tuple)) else None)
            )
            product = db_to_human.get(
                getattr(row, "blood_product", None)
                or (row[1] if isinstance(row, (list, tuple)) else None),
                None,
            )
            if not product:
                continue
            if date_key not in data_by_date:
                data_by_date[date_key] = {}
            if product not in data_by_date[date_key]:
                data_by_date[date_key][product] = 0
            # Use correct field for value
            value = (
                getattr(row, "daily_received", None)
                if hasattr(row, "daily_received")
                else getattr(row, "daily_requested", None)
            )
            if value is None and isinstance(row, (list, tuple)):
                value = row[3] if len(row) > 3 else 0
            data_by_date[date_key][product] += value or 0
        chart_data = []
        current_date = from_date.date()
        end_date = to_date.date()
        while current_date <= end_date:
            date_key = current_date.isoformat()
            chart_point = {
                "date": current_date.isoformat() + "T10:30:00Z",
                "formattedDate": current_date.strftime("%b %d"),
            }
            day_data = data_by_date.get(date_key, {})
            # Only add human-readable keys
            for product in canonical_products:
                chart_point[product] = day_data.get(product, 0)
            print(f"=================={chart_point}===================")
            # Remove any snake_case keys if present (defensive, but should not be needed)
            for k in [
                "whole_blood",
                "red_blood_cells",
                "platelets",
                "fresh_frozen_plasma",
                "cryoprecipitate",
                "albumin",
            ]:
                chart_point.pop(k, None)
            chart_data.append(chart_point)
            current_date += timedelta(days=1)
            print(f"=====================Chart Data: {chart_data}===================")
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
        selected_keys: List[str],  # This argument is not needed, but keep for compatibility
    ) -> List[Dict[str, Any]]:
        """Build chart data with human-readable blood product names as keys."""

        db_to_human = {
            "Whole Blood": "Whole Blood",
            "Red Blood Cells": "Red Blood Cells",
            "Red Cells": "Red Blood Cells",
            "Platelets": "Platelets",
            "Fresh Frozen Plasma": "Fresh Frozen Plasma",
            "Plasma": "Fresh Frozen Plasma",
            "Cryoprecipitate": "Cryoprecipitate",
            "Albumin": "Albumin",
        }
        canonical_products = [
            "Whole Blood",
            "Red Blood Cells",
            "Platelets",
            "Fresh Frozen Plasma",
            "Cryoprecipitate",
            "Albumin",
        ]
        data_by_date = {}
        for row in raw_data:
            date_key = row.request_date if hasattr(row, "request_date") else row[0]
            product = db_to_human.get(
                row.blood_product if hasattr(row, "blood_product") else row[1], None
            )
            if not product:
                continue
            if date_key not in data_by_date:
                data_by_date[date_key] = {}
            if product not in data_by_date[date_key]:
                data_by_date[date_key][product] = 0
            data_by_date[date_key][product] += (
                row.daily_requested if hasattr(row, "daily_requested") else row[3] or 0
            )
        chart_data = []
        current_date = from_date.date()
        end_date = to_date.date()
        while current_date <= end_date:
            date_key = current_date.isoformat()
            chart_point = {
                "date": current_date.isoformat() + "T10:30:00Z",
                "formattedDate": current_date.strftime("%b %d"),
            }
            day_data = data_by_date.get(date_key, {})
            for product in canonical_products:
                chart_point[product] = day_data.get(product, 0)
            chart_data.append(chart_point)
            current_date += timedelta(days=1)
        return chart_data