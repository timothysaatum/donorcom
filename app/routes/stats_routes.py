import asyncio
import time
from typing import List, Optional
from datetime import datetime, timedelta

# FastAPI and database imports
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

# Utility imports for caching and security
from app.schemas.base_schema import BloodProduct, BloodType
from app.utils.cache_manager import cache_key, manual_cache_get, manual_cache_set
from app.utils.permission_checker import require_permission

# Application-specific imports
from app.dependencies import get_db
from app.schemas.stats_schema import (
    ChartMetadata,
    DashboardSummaryResponse,
    DistributionChartResponse,
    RequestChartMetadata,
    RequestChartResponse,
    RequestDirection,
)
from app.services.stats_service import StatsService, RequestTrackingService
from app.models.user import User
from app.utils.logging_config import get_logger, log_performance_metric, LogContext
from app.utils.generic_id import get_user_facility_id, get_user_blood_bank_id

# Initialize logger and router
logger = get_logger(__name__)
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


class RouteHelpers:
    """Helper class for common route functionality."""

    @staticmethod
    def parse_iso_date(date_str: str, field_name: str, user_id: str) -> datetime:
        """Parse ISO date string with proper error handling."""
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            logger.warning(
                f"Invalid {field_name} format provided",
                extra={
                    "event_type": f"invalid_{field_name}",
                    "user_id": user_id,
                    f"{field_name}": date_str,
                },
            )
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {field_name} format. Use ISO 8601 format (e.g., '2024-01-15T00:00:00Z')",
            )

    @staticmethod
    def validate_date_range(from_date: datetime, to_date: datetime, user_id: str):
        """Validate date range constraints."""
        if from_date > to_date:
            logger.warning(
                "Invalid date range - from_date after to_date",
                extra={
                    "event_type": "invalid_date_range",
                    "user_id": user_id,
                    "from_date": from_date.isoformat(),
                    "to_date": to_date.isoformat(),
                },
            )
            raise HTTPException(
                status_code=400,
                detail="The 'from' date cannot be after the 'to' date",
            )

        days_diff = (to_date - from_date).days
        if days_diff > 365:
            logger.warning(
                "Date range too large",
                extra={
                    "event_type": "date_range_too_large",
                    "user_id": user_id,
                    "days_diff": days_diff,
                },
            )
            raise HTTPException(
                status_code=400, detail="Date range cannot exceed 365 days"
            )

    @staticmethod
    def validate_blood_products(blood_products: List[BloodProduct], user_id: str):
        """Validate blood product selections."""
        valid_products = [
            BloodProduct.WHOLE_BLOOD,
            BloodProduct.RED_BLOOD_CELLS,
            BloodProduct.PLATELETS,
            BloodProduct.FRESH_FROZEN_PLASMA,
            BloodProduct.CRYOPRECIPITATE,
            BloodProduct.ALBUMIN,
            BloodProduct.PLASMA,
        ]

        invalid_products = [p for p in blood_products if p not in valid_products]
        if invalid_products:
            logger.warning(
                "Invalid blood product types provided",
                extra={
                    "event_type": "invalid_blood_products",
                    "user_id": user_id,
                    "invalid_products": invalid_products,
                },
            )
            raise HTTPException(
                status_code=400,
                detail=f"Invalid blood product types: {invalid_products}. Valid options: {[p.value for p in valid_products]}",
            )

    @staticmethod
    def validate_blood_types(blood_types: List[BloodType], user_id: str):
        """Validate blood type selections."""
        valid_blood_types = [
            BloodType.A_POSITIVE,
            BloodType.A_NEGATIVE,
            BloodType.B_POSITIVE,
            BloodType.B_NEGATIVE,
            BloodType.AB_POSITIVE,
            BloodType.AB_NEGATIVE,
            BloodType.O_POSITIVE,
            BloodType.O_NEGATIVE,
        ]

        invalid_blood_types = [bt for bt in blood_types if bt not in valid_blood_types]
        if invalid_blood_types:
            logger.warning(
                "Invalid blood types provided",
                extra={
                    "event_type": "invalid_blood_types",
                    "user_id": user_id,
                    "invalid_blood_types": invalid_blood_types,
                },
            )
            raise HTTPException(
                status_code=400,
                detail=f"Invalid blood types: {invalid_blood_types}. Valid options: {[bt.value for bt in valid_blood_types]}",
            )

    @staticmethod
    def build_chart_metadata(
        chart_data: List,
        from_date: datetime,
        to_date: datetime,
        blood_products: Optional[List[BloodProduct]] = None,
        blood_types: Optional[List[BloodType]] = None,
    ) -> ChartMetadata:
        """Build metadata for chart responses."""
        # Convert BloodProduct enums to human-readable names
        meta_blood_products = []
        if blood_products:
            meta_blood_products = [bp.value for bp in blood_products]

        meta_blood_types = None
        if blood_types:
            meta_blood_types = [bt.value for bt in blood_types]

        return ChartMetadata(
            totalRecords=len(chart_data),
            dateRange={
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
            },
            bloodProducts=meta_blood_products,
            bloodTypes=meta_blood_types,
        )



@router.get("/summary", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.inventory.can_view"
        )
    ),
    request: Request = None,
):
    """Get dashboard summary statistics for a facility."""
    start_time = time.time()

    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        logger.info(
            "Dashboard summary request initiated",
            extra={
                "event_type": "dashboard_summary_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
            },
        )

        try:
            facility_id = get_user_facility_id(current_user)
            stats_service = StatsService(db)

            stats_data = await stats_service.get_dashboard_summary(facility_id)

            # Log performance and success
            execution_time = time.time() - start_time
            log_performance_metric(
                operation="dashboard_summary",
                duration_seconds=execution_time,
                additional_metrics={
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                },
            )

            logger.info(
                "Dashboard summary retrieved successfully",
                extra={
                    "event_type": "dashboard_summary_success",
                    "user_id": str(current_user.id),
                    "facility_id": str(facility_id),
                    "execution_time_seconds": round(execution_time, 4),
                },
            )

            return stats_data

        except HTTPException:
            raise
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                "Dashboard summary retrieval failed",
                extra={
                    "event_type": "dashboard_summary_failed",
                    "user_id": str(current_user.id),
                    "execution_time_seconds": round(execution_time, 4),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )


# =============================================================================
# DISTRIBUTION CHART ENDPOINT - SIMPLIFIED
# =============================================================================


@router.get("/distribution-chart", response_model=DistributionChartResponse)
async def distribution_chart(
    from_date: Optional[str] = Query(None, description="Start date in ISO format"),
    to_date: Optional[str] = Query(None, description="End date in ISO format"),
    blood_products: Optional[List[BloodProduct]] = Query(
        None, description="Blood products to include"
    ),
    blood_types: Optional[List[BloodType]] = Query(
        None, description="Blood types to include"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.inventory.manage"
        )
    ),
    request: Request = None,
):
    """Get blood distribution chart data for dashboard visualization."""
    start_time = time.time()

    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        logger.info(
            "Distribution chart request initiated",
            extra={
                "event_type": "distribution_chart_started",
                "user_id": str(current_user.id),
                "from_date": from_date,
                "to_date": to_date,
                "blood_products": (
                    [bp.value for bp in blood_products] if blood_products else None
                ),
                "blood_types": (
                    [bt.value for bt in blood_types] if blood_types else None
                ),
            },
        )

        try:
            blood_bank_id = await get_user_blood_bank_id(db, current_user.id)

            # Parse and validate dates
            parsed_from_date = None
            parsed_to_date = None

            if from_date:
                parsed_from_date = RouteHelpers.parse_iso_date(
                    from_date, "from_date", str(current_user.id)
                )

            if to_date:
                parsed_to_date = RouteHelpers.parse_iso_date(
                    to_date, "to_date", str(current_user.id)
                )

            # Validate date range if both dates provided
            if parsed_from_date and parsed_to_date:
                RouteHelpers.validate_date_range(
                    parsed_from_date, parsed_to_date, str(current_user.id)
                )

            # Validate blood products and types
            if blood_products:
                RouteHelpers.validate_blood_products(
                    blood_products, str(current_user.id)
                )

            if blood_types:
                RouteHelpers.validate_blood_types(blood_types, str(current_user.id))

            # Get chart data using the new service
            stats_service = StatsService(db)
            chart_data = await stats_service.get_distribution_chart_data(
                blood_bank_id=blood_bank_id,
                from_date=parsed_from_date,
                to_date=parsed_to_date,
                selected_blood_products=blood_products,
                selected_blood_types=blood_types,
            )

            # Set actual date range used (with service defaults applied)
            actual_to_date = parsed_to_date or datetime.now()
            actual_from_date = parsed_from_date or (actual_to_date - timedelta(days=7))

            # Build metadata
            metadata = RouteHelpers.build_chart_metadata(
                chart_data,
                actual_from_date,
                actual_to_date,
                blood_products,
                blood_types,
            )

            # Log performance metrics
            execution_time = time.time() - start_time
            log_performance_metric(
                operation="distribution_chart",
                duration_seconds=execution_time,
                additional_metrics={
                    "blood_bank_id": str(blood_bank_id),
                    "user_id": str(current_user.id),
                    "data_points": len(chart_data),
                    "date_range_days": (actual_to_date - actual_from_date).days,
                },
            )

            logger.info(
                "Distribution chart data retrieved successfully",
                extra={
                    "event_type": "distribution_chart_success",
                    "user_id": str(current_user.id),
                    "blood_bank_id": str(blood_bank_id),
                    "execution_time_seconds": round(execution_time, 4),
                    "data_points": len(chart_data),
                },
            )

            return DistributionChartResponse(
                success=True, data=chart_data, meta=metadata
            )

        except HTTPException:
            raise
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                "Distribution chart data retrieval failed",
                extra={
                    "event_type": "distribution_chart_failed",
                    "user_id": str(current_user.id),
                    "execution_time_seconds": round(execution_time, 4),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )


# =============================================================================
# REQUEST CHART ENDPOINT - SIMPLIFIED WITH CACHING
# =============================================================================


@router.get("/request-chart", response_model=RequestChartResponse)
async def get_request_chart_get(
    from_date: Optional[datetime] = Query(None, description="Start date for filtering"),
    to_date: Optional[datetime] = Query(None, description="End date for filtering"),
    blood_products: Optional[List[BloodProduct]] = Query(
        None, description="Blood products to include"
    ),
    blood_types: Optional[List[BloodType]] = Query(
        None, description="Blood types to filter by"
    ),
    request_direction: Optional[RequestDirection] = Query(
        None, description="Filter by sent or received"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.inventory.manage"
        )
    ),
    request: Request = None,
) -> RequestChartResponse:
    """Get blood request chart data with caching and timeout protection."""
    start_time = time.time()

    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        logger.info(
            "Request chart data request initiated",
            extra={
                "event_type": "request_chart_started",
                "user_id": str(current_user.id),
                "from_date": from_date.isoformat() if from_date else None,
                "to_date": to_date.isoformat() if to_date else None,
                "blood_products": (
                    [bp.value for bp in blood_products] if blood_products else None
                ),
                "blood_types": (
                    [bt.value for bt in blood_types] if blood_types else None
                ),
                "request_direction": (
                    request_direction.value if request_direction else None
                ),
            },
        )

        try:
            facility_id = get_user_facility_id(current_user)

            # Simplified date validation (service handles defaults)
            if from_date and to_date and from_date >= to_date:
                raise HTTPException(
                    status_code=400, detail="from_date must be before to_date"
                )

            if from_date and to_date:
                days_diff = (to_date - from_date).days
                if days_diff > 365:
                    raise HTTPException(
                        status_code=400, detail="Date range cannot exceed 365 days"
                    )

            # Generate cache key
            cache_key_str = cache_key(
                "request_chart",
                facility_id,
                from_date.isoformat() if from_date else None,
                to_date.isoformat() if to_date else None,
                tuple(bp.value for bp in blood_products) if blood_products else None,
                tuple(bt.value for bt in blood_types) if blood_types else None,
                request_direction.value if request_direction else None,
            )

            # Check cache first
            cached_result = manual_cache_get(cache_key_str)
            if cached_result:
                logger.info(
                    "Request chart data returned from cache",
                    extra={
                        "event_type": "request_chart_cache_hit",
                        "user_id": str(current_user.id),
                        "execution_time_seconds": round(time.time() - start_time, 4),
                    },
                )
                return cached_result

            # Fetch fresh data using new service with timeout
            chart_data = await asyncio.wait_for(
                RequestTrackingService(db).get_request_chart_data(
                    facility_id=facility_id,
                    from_date=from_date,
                    to_date=to_date,
                    selected_blood_products=blood_products,
                    selected_blood_types=blood_types,
                    request_direction=(
                        request_direction.value if request_direction else None
                    ),
                ),
                timeout=30.0,
            )

            # Build metadata
            actual_from_date = from_date or (datetime.now() - timedelta(days=7))
            actual_to_date = to_date or datetime.now()

            metadata = RequestChartMetadata(
                totalRecords=len(chart_data),
                dateRange={
                    "from": actual_from_date.isoformat(),
                    "to": actual_to_date.isoformat(),
                },
                bloodProducts=(
                    [bp.value for bp in blood_products] if blood_products else []
                ),
                bloodTypes=[bt.value for bt in blood_types] if blood_types else None,
            )

            response = RequestChartResponse(
                success=True, data=chart_data, meta=metadata
            )

            # Cache the result
            manual_cache_set(cache_key_str, response, ttl=300)

            # Log performance
            execution_time = time.time() - start_time
            log_performance_metric(
                operation="request_chart",
                duration_seconds=execution_time,
                additional_metrics={
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                    "data_points": len(chart_data),
                    "cached": False,
                },
            )

            logger.info(
                "Request chart data retrieved successfully",
                extra={
                    "event_type": "request_chart_success",
                    "user_id": str(current_user.id),
                    "facility_id": str(facility_id),
                    "execution_time_seconds": round(execution_time, 4),
                    "data_points": len(chart_data),
                    "cached": False,
                },
            )

            return response

        except HTTPException:
            raise
        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            logger.error(
                "Request chart data retrieval timed out",
                extra={
                    "event_type": "request_chart_timeout",
                    "user_id": str(current_user.id),
                    "execution_time_seconds": round(execution_time, 4),
                    "timeout_seconds": 30.0,
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail="Request processing timed out. Please try again or reduce the date range.",
            )
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                "Request chart data retrieval failed",
                extra={
                    "event_type": "request_chart_failed",
                    "user_id": str(current_user.id),
                    "execution_time_seconds": round(execution_time, 4),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )
