from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional, Type
from abc import ABC, abstractmethod
import uuid
from sqlalchemy.exc import SQLAlchemyError
from app.utils.logging_config import get_logger
from app.models.request_model import BloodRequest, DashboardDailySummary
from app.models.distribution_model import BloodDistribution
from app.schemas.base_schema import BloodProduct

logger = get_logger(__name__)


class BloodProductProcessor:
    """Utility class for processing blood product selections and mappings."""

    # Static mappings for blood product conversions
    ENUM_TO_HUMAN = {
        "Whole Blood": "Whole Blood",
        "Red Blood Cells": "Red Blood Cells",
        "Red Cells": "Red Blood Cells",  # Map variant to canonical
        "Platelets": "Platelets",
        "Fresh Frozen Plasma": "Fresh Frozen Plasma",
        "Plasma": "Fresh Frozen Plasma",  # Map variant to canonical
        "Cryoprecipitate": "Cryoprecipitate",
        "Albumin": "Albumin",
    }

    SNAKE_CASE_TO_HUMAN = {
        "whole_blood": "Whole Blood",
        "red_blood_cells": "Red Blood Cells",
        "platelets": "Platelets",
        "fresh_frozen_plasma": "Fresh Frozen Plasma",
        "cryoprecipitate": "Cryoprecipitate",
        "albumin": "Albumin",
    }

    DEFAULT_PRODUCTS = ["Whole Blood", "Red Blood Cells", "Platelets"]

    @classmethod
    def process_blood_products(
        cls, selected_blood_products: Optional[List]
    ) -> List[str]:
        """Process and validate blood product selections, returning human-readable names."""
        # Only use defaults if None is passed (not if empty list [])
        if selected_blood_products is None:
            return cls.DEFAULT_PRODUCTS.copy()

        # If empty list is explicitly provided, return empty (user selected nothing)
        if not selected_blood_products:
            return []

        selected_products = []
        for product in selected_blood_products:
            if hasattr(product, "value"):  # BloodProduct enum
                selected_products.append(product.value)
            else:  # String
                product_str = str(product).strip()
                if product_str in cls.SNAKE_CASE_TO_HUMAN:
                    selected_products.append(cls.SNAKE_CASE_TO_HUMAN[product_str])
                else:
                    # Try to normalize using BloodProduct
                    try:
                        normalized = BloodProduct.normalize_product_name(product_str)
                        selected_products.append(normalized)
                    except:
                        logger.warning(f"Invalid blood product: {product_str}")
                        continue

        if not selected_products:
            logger.info(
                "No valid blood products after processing, returning empty list"
            )
            return []

        processed = list(set(selected_products))  # Remove duplicates
        logger.info(f"Processed blood products: {processed}")
        return processed

    @classmethod
    def get_db_product_names(cls, selected_product_names: List[str]) -> List[str]:
        """Map human-readable product names to database names.

        NOTE: Variants like 'Red Cells' vs 'Red Blood Cells' should be normalized
        at the database level or during data entry, not during querying.
        This ensures the chart only shows what the user explicitly requested.
        """
        # Return the product names as-is, no automatic variant addition
        return list(set(selected_product_names))  # Remove duplicates only

    @classmethod
    def process_blood_types(
        cls, selected_blood_types: Optional[List]
    ) -> Optional[List[str]]:
        """Process and validate blood type selections."""
        if not selected_blood_types:
            return None

        blood_types = []
        for bt in selected_blood_types:
            if hasattr(bt, "value"):
                blood_types.append(bt.value)
            else:
                blood_types.append(str(bt))
        return blood_types


class ChartDataBuilder:
    """Utility class for building chart data from raw database results."""

    @staticmethod
    def build_chart_data(
        raw_data: List,
        from_date: datetime,
        to_date: datetime,
        selected_products: List[str],
        date_field_names: List[str] = ["distribution_date", "request_date"],
        value_field_names: List[str] = ["daily_received", "daily_requested"],
    ) -> List[Dict[str, Any]]:
        """Build chart data with only selected blood products."""

        db_to_human = BloodProductProcessor.ENUM_TO_HUMAN

        logger.info(f"Building chart for selected products: {selected_products}")
        logger.debug(f"Date range: {from_date.date()} to {to_date.date()}")

        # Collect data by date for selected products only
        data_by_date = {}
        for row in raw_data:
            # Extract date (handle different query result formats)
            date_key = None
            for field_name in date_field_names:
                if hasattr(row, field_name):
                    date_key = getattr(row, field_name)
                    break
            if not date_key and isinstance(row, (list, tuple)):
                date_key = row[0]

            if not date_key:
                continue

            # Convert date to string for consistent keying
            if isinstance(date_key, str):
                date_str = date_key
            else:
                date_str = date_key.isoformat()

            # Extract product name and normalize it
            db_product_name = getattr(row, "blood_product", None) or (
                row[1] if isinstance(row, (list, tuple)) else None
            )

            human_product_name = db_to_human.get(db_product_name, db_product_name)

            logger.debug(
                f"Processing row: date={date_str}, db_product={db_product_name}, "
                f"human_product={human_product_name}, in_selected={human_product_name in selected_products}"
            )

            # Skip if product not in selected products
            if not human_product_name or human_product_name not in selected_products:
                logger.debug(
                    f"Skipping product {human_product_name} - not in selected list"
                )
                continue

            # Initialize date entry if needed
            if date_str not in data_by_date:
                data_by_date[date_str] = {}
            if human_product_name not in data_by_date[date_str]:
                data_by_date[date_str][human_product_name] = 0

            # Extract quantity (handle different field names)
            quantity = None
            for field_name in value_field_names:
                if hasattr(row, field_name):
                    quantity = getattr(row, field_name)
                    break
            if quantity is None and isinstance(row, (list, tuple)) and len(row) > 3:
                quantity = row[3]

            data_by_date[date_str][human_product_name] += quantity or 0

        # Generate chart data points
        chart_data = []
        current_date = from_date.date()
        end_date = to_date.date()

        logger.debug(f"Generating data points from {current_date} to {end_date}")

        while current_date <= end_date:
            date_key = current_date.isoformat()
            chart_point = {
                "date": current_date.isoformat() + "T10:30:00Z",
                "formattedDate": current_date.strftime("%b %d"),
            }

            day_data = data_by_date.get(date_key, {})

            # Add ONLY the selected products
            for product_name in selected_products:
                chart_point[product_name] = day_data.get(product_name, 0)

            chart_data.append(chart_point)
            current_date += timedelta(days=1)

        logger.info(
            f"Generated {len(chart_data)} chart points with {len(selected_products)} products. "
            f"Total data rows processed: {len(data_by_date)}"
        )

        return chart_data


class BaseChartService(ABC):
    """Abstract base class for chart data services with common functionality."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _validate_date_range(
        self, from_date: Optional[datetime], to_date: Optional[datetime]
    ) -> tuple[datetime, datetime]:
        """Validate and set default date range."""
        original_from = from_date
        original_to = to_date

        if to_date is None:
            to_date = datetime.now().replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
        if from_date is None:
            from_date = to_date - timedelta(days=7)
            from_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)

        if from_date >= to_date:
            raise ValueError("from_date must be before to_date")

        date_diff = (to_date - from_date).days
        if date_diff > 365:
            raise ValueError("Date range cannot exceed 365 days")

        logger.info(
            f"Date range validated - Original: ({original_from}, {original_to}) -> "
            f"Used: ({from_date.date()}, {to_date.date()}) [{date_diff} days]"
        )

        return from_date, to_date

    def _log_performance(
        self, operation: str, start_time: datetime, data_count: int, raw_count: int
    ):
        """Log performance metrics."""
        execution_time = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"{operation} chart data generated: {data_count} points, "
            f"{raw_count} raw records, {execution_time:.3f}s"
        )

    @abstractmethod
    async def _build_query_conditions(
        self,
        facility_id: uuid.UUID,
        from_date: datetime,
        to_date: datetime,
        db_product_names: List[str],
        blood_types: Optional[List[str]],
        **kwargs,
    ) -> List:
        """Build query conditions specific to the service."""
        pass

    @abstractmethod
    async def _execute_query(self, query_conditions: List) -> List:
        """Execute the database query specific to the service."""
        pass

    @abstractmethod
    def _get_chart_data_builder_config(self) -> Dict[str, List[str]]:
        """Get configuration for the chart data builder."""
        pass

    async def get_chart_data(
        self,
        facility_id: uuid.UUID,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        selected_blood_products: Optional[List] = None,
        selected_blood_types: Optional[List] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Generic method to get chart data."""
        start_time = datetime.now()

        try:
            if not facility_id:
                raise ValueError("facility_id is required")

            # Validate and set date range
            from_date, to_date = self._validate_date_range(from_date, to_date)

            # Process blood products and types
            selected_product_names = BloodProductProcessor.process_blood_products(
                selected_blood_products
            )
            selected_blood_types_values = BloodProductProcessor.process_blood_types(
                selected_blood_types
            )

            # Get database product names
            db_product_names = BloodProductProcessor.get_db_product_names(
                selected_product_names
            )

            # Build and execute query
            query_conditions = await self._build_query_conditions(
                facility_id,
                from_date,
                to_date,
                db_product_names,
                selected_blood_types_values,
                **kwargs,
            )

            raw_data = await self._execute_query(query_conditions)

            # Build chart data
            builder_config = self._get_chart_data_builder_config()
            chart_data = ChartDataBuilder.build_chart_data(
                raw_data, from_date, to_date, selected_product_names, **builder_config
            )

            # Log performance
            self._log_performance(
                self.__class__.__name__, start_time, len(chart_data), len(raw_data)
            )

            return chart_data

        except SQLAlchemyError as e:
            logger.error(f"Database error in {self.__class__.__name__}: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in {self.__class__.__name__}: {str(e)}")
            raise


class StatsService(BaseChartService):
    """Service for handling blood distribution statistics."""

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
        """
        Get dashboard summary with today vs yesterday comparisons.

        SCALABLE HYBRID APPROACH:
        1. Try to get TODAY's data from DashboardDailySummary (fast, cached)
        2. If not found or stale (>5 min old), trigger immediate refresh
        3. Return data from cache after refresh

        This scales to thousands of users because:
        - Most requests hit the cache (O(1) lookup)
        - Cache is automatically refreshed every 5 minutes by scheduler
        - Only triggers refresh if cache is missing/stale
        - Single facility query (no table scans)
        """
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Try to get today's summary from cache first (FAST PATH)
        today_query = select(DashboardDailySummary).where(
            and_(
                DashboardDailySummary.facility_id == facility_id,
                DashboardDailySummary.date == today,
            )
        )
        today_summary = (await self.db.execute(today_query)).scalar_one_or_none()

        # Check if cache is stale (updated more than 5 minutes ago)
        cache_is_stale = False
        if today_summary and today_summary.updated_at:
            cache_age_seconds = (
                datetime.now() - today_summary.updated_at
            ).total_seconds()
            cache_is_stale = cache_age_seconds > 300  # 5 minutes

        # If no cache or stale, trigger immediate refresh (SLOW PATH - rare)
        if not today_summary or cache_is_stale:
            logger.info(
                f"Dashboard cache {'missing' if not today_summary else 'stale'} "
                f"for facility {facility_id}, triggering refresh"
            )
            try:
                from app.services.dashboard_service import (
                    refresh_facility_dashboard_metrics,
                )

                await refresh_facility_dashboard_metrics(self.db, facility_id, today)

                # Re-fetch the refreshed summary
                today_summary = (
                    await self.db.execute(today_query)
                ).scalar_one_or_none()
            except Exception as refresh_error:
                logger.error(f"Failed to refresh dashboard cache: {refresh_error}")
                # Continue with stale data or zeros

        # Get yesterday's summary for comparison (always from cache)
        yesterday_query = select(DashboardDailySummary).where(
            and_(
                DashboardDailySummary.facility_id == facility_id,
                DashboardDailySummary.date == yesterday,
            )
        )
        yesterday_summary = (
            await self.db.execute(yesterday_query)
        ).scalar_one_or_none()

        # If still no today summary after refresh, return zeros
        if not today_summary:
            logger.warning(f"No dashboard data available for facility {facility_id}")
            return {
                "stock": {"value": 0, "change": 0.0, "direction": "neutral"},
                "transferred": {"value": 0, "change": 0.0, "direction": "neutral"},
                "requests": {"value": 0, "change": 0.0, "direction": "neutral"},
            }

        # Calculate changes using yesterday's cached data
        y_stock = yesterday_summary.total_stock if yesterday_summary else 0
        y_transferred = yesterday_summary.total_transferred if yesterday_summary else 0
        y_requests = yesterday_summary.total_requests if yesterday_summary else 0

        stock_change, stock_dir = self.calculate_change(
            today_summary.total_stock, y_stock
        )
        transferred_change, transferred_dir = self.calculate_change(
            today_summary.total_transferred, y_transferred
        )
        requests_change, requests_dir = self.calculate_change(
            today_summary.total_requests, y_requests
        )

        logger.debug(
            f"Dashboard summary for facility {facility_id}: "
            f"stock={today_summary.total_stock} (was {y_stock}), "
            f"transferred={today_summary.total_transferred} (was {y_transferred}), "
            f"requests={today_summary.total_requests} (was {y_requests})"
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
        """Get blood distribution chart data."""
        return await self.get_chart_data(
            blood_bank_id,
            from_date,
            to_date,
            selected_blood_products,
            selected_blood_types,
        )

    async def _build_query_conditions(
        self,
        facility_id: uuid.UUID,
        from_date: datetime,
        to_date: datetime,
        db_product_names: List[str],
        blood_types: Optional[List[str]],
        **kwargs,
    ) -> List:
        """Build query conditions for distribution data."""

        logger.info(
            f"Building distribution query: facility={facility_id}, "
            f"date_range={from_date.date()} to {to_date.date()}, "
            f"products={db_product_names}"
        )

        # Convert timezone-aware datetimes to naive for database comparison
        # The database column is TIMESTAMP WITHOUT TIME ZONE
        from_date_naive = (
            from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
        )
        to_date_naive = to_date.replace(tzinfo=None) if to_date.tzinfo else to_date

        conditions = [
            BloodDistribution.dispatched_from_id == facility_id,
            BloodDistribution.date_delivered.is_not(None),
            BloodDistribution.date_delivered >= from_date_naive,
            BloodDistribution.date_delivered <= to_date_naive,
            BloodDistribution.status.in_(["delivered", "in transit"]),
        ]

        if db_product_names:
            conditions.append(BloodDistribution.blood_product.in_(db_product_names))
            logger.info(
                f"Distribution query - Filtering by products: {db_product_names}"
            )
        else:
            logger.info(
                "Distribution query - No product filter (will return all products)"
            )

        if blood_types:
            conditions.append(BloodDistribution.blood_type.in_(blood_types))
            logger.info(f"Distribution query - Filtering by blood types: {blood_types}")

        return conditions

    async def _execute_query(self, query_conditions: List) -> List:
        """Execute the distribution query."""
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
        rows = result.fetchall()

        logger.info(f"Distribution query returned {len(rows)} rows")
        if rows:
            products_found = set(row.blood_product for row in rows)
            logger.info(f"Products found in results: {products_found}")

        return rows

    def _get_chart_data_builder_config(self) -> Dict[str, List[str]]:
        """Get configuration for the chart data builder."""
        return {
            "date_field_names": ["distribution_date"],
            "value_field_names": ["daily_received"],
        }


class RequestTrackingService(BaseChartService):
    """Service for handling blood request tracking and analytics."""

    async def get_request_chart_data(
        self,
        facility_id: uuid.UUID,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        selected_blood_products: Optional[List] = None,
        selected_blood_types: Optional[List] = None,
        request_direction: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get blood request chart data."""
        return await self.get_chart_data(
            facility_id,
            from_date,
            to_date,
            selected_blood_products,
            selected_blood_types,
            request_direction=request_direction,
        )

    async def _build_query_conditions(
        self,
        facility_id: uuid.UUID,
        from_date: datetime,
        to_date: datetime,
        db_product_names: List[str],
        blood_types: Optional[List[str]],
        **kwargs,
    ) -> List:
        """Build query conditions for request data."""
        request_direction = kwargs.get("request_direction")

        logger.info(
            f"Building request query: facility={facility_id}, "
            f"date_range={from_date.date()} to {to_date.date()}, "
            f"products={db_product_names}, direction={request_direction}"
        )

        # Convert timezone-aware datetimes to naive for database comparison
        # The database column is TIMESTAMP WITHOUT TIME ZONE
        from_date_naive = (
            from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
        )
        to_date_naive = to_date.replace(tzinfo=None) if to_date.tzinfo else to_date

        conditions = [
            BloodRequest.created_at >= from_date_naive,
            BloodRequest.created_at <= to_date_naive,
        ]

        # Handle request direction
        if request_direction == "sent":
            conditions.append(BloodRequest.source_facility_id == facility_id)
        elif request_direction == "received":
            conditions.append(BloodRequest.facility_id == facility_id)
        else:
            conditions.append(
                or_(
                    BloodRequest.source_facility_id == facility_id,
                    BloodRequest.facility_id == facility_id,
                )
            )

        if db_product_names:
            conditions.append(BloodRequest.blood_product.in_(db_product_names))
            logger.info(f"Request query - Filtering by products: {db_product_names}")
        else:
            logger.info("Request query - No product filter (will return all products)")

        if blood_types:
            conditions.append(BloodRequest.blood_type.in_(blood_types))
            logger.info(f"Request query - Filtering by blood types: {blood_types}")

        return conditions

    async def _execute_query(self, query_conditions: List) -> List:
        """Execute the request query."""
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
        rows = result.fetchall()

        logger.info(f"Request query returned {len(rows)} rows")
        if rows:
            products_found = set(row.blood_product for row in rows)
            logger.info(f"Products found in results: {products_found}")

        return rows

    def _get_chart_data_builder_config(self) -> Dict[str, List[str]]:
        """Get configuration for the chart data builder."""
        return {
            "date_field_names": ["request_date"],
            "value_field_names": ["daily_requested"],
        }
