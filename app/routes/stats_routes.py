# =============================================================================
# STATS ROUTES MODULE
# =============================================================================
# This module provides FastAPI routes for blood bank dashboard statistics and
# analytics. It includes endpoints for:
# - Dashboard summary (stock, transfers, requests comparison)
# - Monthly transfer statistics and trends
# - Blood product distribution charts
# - Request tracking and analytics
#
# All endpoints include comprehensive logging, performance monitoring, caching,
# and proper error handling. Security is enforced through permission-based
# access control.
# =============================================================================

import asyncio
import time

# Utility imports for caching and security
from app.schemas.base_schema import BloodProduct, BloodType
from app.utils.cache_manager import cache_key, manual_cache_get, manual_cache_set
from app.utils.permission_checker import require_permission

# FastAPI and database imports
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import date, datetime, timedelta

# Application-specific imports
from app.dependencies import get_db
from app.schemas.stats_schema import (
    ChartMetadata,  # Chart metadata schema
    DashboardSummaryResponse,  # Dashboard summary response model
    DistributionChartResponse,  # Distribution chart response model
    MonthlyTransferStatsResponse,  # Monthly stats response model
    BloodProductBreakdownResponse,
    RequestChartMetadata,
    RequestChartResponse,
    RequestDirection,  # Product breakdown response model
    TransferTrendsResponse,  # Transfer trends response model
)
from app.services.stats_service import StatsService, RequestTrackingService
from app.models.user import User
from app.utils.logging_config import get_logger, log_performance_metric, LogContext
from app.utils.generic_id import get_user_facility_id, get_user_blood_bank_id

# Initialize logger for this module
logger = get_logger(__name__)

# Create router with dashboard prefix and tags for API documentation
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# =============================================================================
# DASHBOARD SUMMARY ENDPOINT
# =============================================================================
# Provides high-level statistics comparing today vs yesterday for:
# - Total stock levels
# - Total blood transfers
# - Total blood requests
# Each metric includes percentage change and trend direction (up/down/neutral)
# =============================================================================


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
    """
    Get dashboard summary statistics for a facility.

    Returns today vs yesterday comparison for:
    - Total blood units in stock
    - Total blood units transferred
    - Total blood requests made

    Each metric includes:
    - Current value
    - Percentage change from yesterday
    - Trend direction (up/down/neutral)

    Required Permissions:
    - facility.manage OR laboratory.manage OR blood.inventory.can_view

    Returns:
        DashboardSummaryResponse: Summary statistics with trend analysis

    Example Response:
    {
        "total_in_stock": {
            "value": 150,
            "change": 12.5,
            "direction": "up"
        },
        "total_transferred": {
            "value": 25,
            "change": -8.3,
            "direction": "down"
        },
        "total_requested": {
            "value": 30,
            "change": 0.0,
            "direction": "neutral"
        }
    }
    """
    import time

    # Start performance monitoring
    start_time = time.time()

    # Set up logging context with request/user information
    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        # Log the start of the dashboard summary request
        logger.info(
            "Dashboard summary request initiated",
            extra={
                "event_type": "dashboard_summary_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
            },
        )

        try:
            # Get the facility ID associated with the current user
            # This determines which facility's statistics to retrieve
            facility_id = get_user_facility_id(current_user)

            # Initialize the statistics service with database session
            stats_service = StatsService(db)

            logger.debug(
                "Fetching dashboard summary data",
                extra={
                    "event_type": "dashboard_summary_fetch",
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                },
            )

            # Retrieve dashboard summary data (today vs yesterday comparison)
            # This includes stock levels, transfers, and requests with percentage changes
            stats_data = await stats_service.get_dashboard_summary(facility_id)

            # Calculate and log performance metrics
            execution_time = time.time() - start_time
            log_performance_metric(
                operation="dashboard_summary",
                duration_seconds=execution_time,
                additional_metrics={
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                },
            )

            # Log successful completion with key metrics
            logger.info(
                "Dashboard summary retrieved successfully",
                extra={
                    "event_type": "dashboard_summary_success",
                    "user_id": str(current_user.id),
                    "facility_id": str(facility_id),
                    "execution_time_seconds": round(execution_time, 4),
                    "total_in_stock": (
                        stats_data["stock"]["value"]
                        if stats_data and stats_data.get("stock")
                        else 0
                    ),
                    "total_transferred": (
                        stats_data["transferred"]["value"]
                        if stats_data and stats_data.get("transferred")
                        else 0
                    ),
                    "total_requested": (
                        stats_data["requests"]["value"]
                        if stats_data and stats_data.get("requests")
                        else 0
                    ),
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
# MONTHLY TRANSFER STATISTICS ENDPOINT
# =============================================================================
# Provides monthly aggregated statistics for blood transfers to/from a facility.
# Data is suitable for monthly trend analysis and year-over-year comparisons.
# Supports filtering by year and specific blood product types.
# =============================================================================


@router.get("/monthly-transfers", response_model=MonthlyTransferStatsResponse)
async def monthly_transfer_stats(
    year: Optional[int] = Query(
        None, description="Year to get statistics for (defaults to current year)"
    ),
    blood_product_types: Optional[List[BloodProduct]] = Query(
        None, description="Filter by specific blood product types"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.inventory.can_view"
        )
    ),
    request: Request = None,
):
    """
    Get monthly blood transfer statistics for the current user's facility.

    This endpoint provides monthly aggregated data showing the total number
    of blood units transferred to the facility. The data spans a full 12-month
    period, with zero values for months with no transfers.

    Query Parameters:
    - year: Year to retrieve statistics for (optional, defaults to current year)
      Range: Typically current year or recent years
    - blood_product_types: Filter results by specific blood product types (optional)
      Available: whole_blood, red_blood_cells, platelets, fresh_frozen_plasma,
                 cryoprecipitate, albumin

    Returns:
        MonthlyTransferStatsResponse: 12-month dataset with monthly totals

    Required Permissions:
    - facility.manage OR laboratory.manage OR blood.inventory.can_view

    Data Structure:
    Each month includes:
    - month: Full month name (e.g., "January")
    - month_number: Numeric month (1-12)
    - total_units: Number of blood units transferred
    - year: Year for the data point

    Use Cases:
    - Monthly trend analysis
    - Year-over-year comparisons
    - Seasonal pattern identification
    - Resource planning and forecasting
    """
    import time

    # Start performance monitoring
    start_time = time.time()

    # Initialize logging context
    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        # Set default year to current year if not provided
        if year is None:
            year = date.today().year

        # Log the start of monthly transfer stats request
        logger.info(
            "Monthly transfer stats request initiated",
            extra={
                "event_type": "monthly_transfer_stats_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "requested_year": year,
                "blood_product_types": blood_product_types,
            },
        )

        try:
            facility_id = get_user_facility_id(current_user)

            # Validate year range
            current_year = date.today().year
            if year < 2000 or year > current_year + 1:
                logger.warning(
                    "Invalid year parameter provided",
                    extra={
                        "event_type": "invalid_year_parameter",
                        "user_id": str(current_user.id),
                        "requested_year": year,
                        "valid_range": f"2000-{current_year + 1}",
                    },
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Year must be between 2000 and {current_year + 1}",
                )

            stats_service = StatsService(db)

            logger.debug(
                "Fetching monthly transfer statistics",
                extra={
                    "event_type": "monthly_transfer_stats_fetch",
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                    "year": year,
                    "blood_product_types": blood_product_types,
                },
            )

            monthly_data = await stats_service.get_monthly_transfer_stats(
                facility_id=facility_id,
                year=year,
                blood_product_types=blood_product_types,
            )

            # Calculate total units for the year
            total_units_year = sum(month["total_units"] for month in monthly_data)

            # Log performance metric
            execution_time = time.time() - start_time
            log_performance_metric(
                operation="monthly_transfer_stats",
                duration_seconds=execution_time,
                additional_metrics={
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                    "year": year,
                    "months_returned": len(monthly_data),
                    "total_units_year": total_units_year,
                },
            )

            logger.info(
                "Monthly transfer stats retrieved successfully",
                extra={
                    "event_type": "monthly_transfer_stats_success",
                    "user_id": str(current_user.id),
                    "facility_id": str(facility_id),
                    "year": year,
                    "execution_time_seconds": round(execution_time, 4),
                    "months_returned": len(monthly_data),
                    "total_units_year": total_units_year,
                    "blood_product_types": blood_product_types,
                },
            )

            return MonthlyTransferStatsResponse(
                data=monthly_data,
                total_units_year=total_units_year,
                facility_id=facility_id,
                year=year,
                blood_product_types=blood_product_types,
            )

        except HTTPException:
            raise
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                "Monthly transfer stats retrieval failed",
                extra={
                    "event_type": "monthly_transfer_stats_failed",
                    "user_id": str(current_user.id),
                    "year": year,
                    "execution_time_seconds": round(execution_time, 4),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )


@router.get("/blood-product-breakdown", response_model=BloodProductBreakdownResponse)
async def blood_product_breakdown(
    year: Optional[int] = Query(
        None, description="Year to get statistics for (defaults to current year)"
    ),
    month: Optional[int] = Query(
        None, ge=1, le=12, description="Optional month filter (1-12)"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.inventory.can_view"
        )
    ),
    request: Request = None,
):
    """
    Breakdown of blood transfers by product type for the current user's facility.

    Provides insights into which blood products are most frequently transferred.
    """
    import time

    start_time = time.time()

    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        # Default to current year if not provided
        if year is None:
            year = date.today().year

        logger.info(
            "Blood product breakdown request initiated",
            extra={
                "event_type": "blood_product_breakdown_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "requested_year": year,
                "requested_month": month,
            },
        )

        try:
            facility_id = get_user_facility_id(current_user)

            # Validate year range
            current_year = date.today().year
            if year < 2024 or year > current_year + 1:
                logger.warning(
                    "Invalid year parameter for blood product breakdown",
                    extra={
                        "event_type": "invalid_year_breakdown",
                        "user_id": str(current_user.id),
                        "requested_year": year,
                        "valid_range": f"2024-{current_year + 1}",
                    },
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Year must be between 2024 and {current_year + 1}",
                )

            # Validate month if provided
            if month is not None and (month < 1 or month > 12):
                logger.warning(
                    "Invalid month parameter provided",
                    extra={
                        "event_type": "invalid_month_parameter",
                        "user_id": str(current_user.id),
                        "requested_month": month,
                    },
                )
                raise HTTPException(
                    status_code=400, detail="Month must be between 1 and 12"
                )

            stats_service = StatsService(db)

            logger.debug(
                "Fetching blood product breakdown data",
                extra={
                    "event_type": "blood_product_breakdown_fetch",
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                    "year": year,
                    "month": month,
                },
            )

            breakdown_data = await stats_service.get_blood_product_breakdown(
                facility_id=facility_id, year=year, month=month
            )

            # Log performance metric
            execution_time = time.time() - start_time
            log_performance_metric(
                operation="blood_product_breakdown",
                duration_seconds=execution_time,
                additional_metrics={
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                    "year": year,
                    "month": month,
                    "breakdown_items": len(breakdown_data) if breakdown_data else 0,
                },
            )

            logger.info(
                "Blood product breakdown retrieved successfully",
                extra={
                    "event_type": "blood_product_breakdown_success",
                    "user_id": str(current_user.id),
                    "facility_id": str(facility_id),
                    "year": year,
                    "month": month,
                    "execution_time_seconds": round(execution_time, 4),
                    "breakdown_items": len(breakdown_data) if breakdown_data else 0,
                },
            )

            return BloodProductBreakdownResponse(
                data=breakdown_data, facility_id=facility_id, year=year, month=month
            )

        except HTTPException:
            raise
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                "Blood product breakdown retrieval failed",
                extra={
                    "event_type": "blood_product_breakdown_failed",
                    "user_id": str(current_user.id),
                    "year": year,
                    "month": month,
                    "execution_time_seconds": round(execution_time, 4),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )


@router.get("/transfer-trends", response_model=TransferTrendsResponse)
async def transfer_trends(
    days: int = Query(
        30, ge=1, le=365, description="Number of days to include in the trend (1-365)"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.inventory.can_view"
        )
    ),
    request: Request = None,
):
    """
    Daily transfer trends for the current user's facility over the last N days.

    Useful for creating short-term trend analysis and identifying patterns.
    """
    import time

    start_time = time.time()

    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        logger.info(
            "Transfer trends request initiated",
            extra={
                "event_type": "transfer_trends_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "requested_days": days,
            },
        )

        try:
            facility_id = get_user_facility_id(current_user)

            # Validate days parameter (already handled by Query validation, but log it)
            if days < 1 or days > 365:
                logger.warning(
                    "Invalid days parameter for transfer trends",
                    extra={
                        "event_type": "invalid_days_parameter",
                        "user_id": str(current_user.id),
                        "requested_days": days,
                    },
                )
                raise HTTPException(
                    status_code=400, detail="Days must be between 1 and 365"
                )

            stats_service = StatsService(db)

            logger.debug(
                "Fetching transfer trends data",
                extra={
                    "event_type": "transfer_trends_fetch",
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                    "days": days,
                },
            )

            trends_data = await stats_service.get_transfer_trends(
                facility_id=facility_id, days=days
            )

            # Calculate period dates
            end_date = date.today()
            start_date = end_date - timedelta(days=days)

            # Log performance metric
            execution_time = time.time() - start_time
            log_performance_metric(
                operation="transfer_trends",
                duration_seconds=execution_time,
                additional_metrics={
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                    "days": days,
                    "trend_data_points": len(trends_data) if trends_data else 0,
                },
            )

            logger.info(
                "Transfer trends retrieved successfully",
                extra={
                    "event_type": "transfer_trends_success",
                    "user_id": str(current_user.id),
                    "facility_id": str(facility_id),
                    "days": days,
                    "execution_time_seconds": round(execution_time, 4),
                    "period_start": start_date.isoformat(),
                    "period_end": end_date.isoformat(),
                    "trend_data_points": len(trends_data) if trends_data else 0,
                },
            )

            return TransferTrendsResponse(
                data=trends_data,
                facility_id=facility_id,
                days=days,
                period_start=start_date.isoformat(),
                period_end=end_date.isoformat(),
            )

        except HTTPException:
            raise
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                "Transfer trends retrieval failed",
                extra={
                    "event_type": "transfer_trends_failed",
                    "user_id": str(current_user.id),
                    "days": days,
                    "execution_time_seconds": round(execution_time, 4),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )


# =============================================================================
# BLOOD DISTRIBUTION CHART ENDPOINT
# =============================================================================
# Provides time-series data for blood distribution visualization.
# Supports filtering by date range, blood products, and blood types.
# Data is returned as daily aggregated values suitable for chart rendering.
# =============================================================================


@router.get("/distribution-chart", response_model=DistributionChartResponse)
async def distribution_chart(
    from_date: Optional[str] = Query(
        None, description="Start date in ISO format (defaults to 7 days ago)"
    ),
    to_date: Optional[str] = Query(
        None, description="End date in ISO format (defaults to today)"
    ),
    blood_products: Optional[List[BloodProduct]] = Query(
        None,
        description="List of blood product keys to include (e.g., whole_blood,platelets)",
    ),
    blood_types: Optional[List[BloodType]] = Query(
        None,
        description="List of blood types to include (e.g., A+, B-, O+)",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_permission(
            "facility.manage", "laboratory.manage", "blood.inventory.manage"
        )
    ),
    request: Request = None,
):
    """
    Get blood distribution chart data for dashboard visualization.

    This endpoint retrieves daily blood distribution data aggregated by product type
    and blood type over a specified date range. The data is optimized for chart
    rendering with proper time-series formatting.

    Query Parameters:
    - from_date: Start date in ISO 8601 format (optional, defaults to 7 days ago)
      Format: "2024-01-15T00:00:00Z" or "2024-01-15T00:00:00+00:00"
    - to_date: End date in ISO 8601 format (optional, defaults to today)
      Format: "2024-01-22T23:59:59Z" or "2024-01-22T23:59:59+00:00"
    - blood_products: List of blood product types to include (optional)
      Available: whole_blood, red_blood_cells, platelets, fresh_frozen_plasma,
                 cryoprecipitate, albumin
    - blood_types: List of blood types to include (optional)
      Available: A+, A-, B+, B-, AB+, AB-, O+, O-

    Returns:
        DistributionChartResponse: Time-series data with daily distribution amounts

    Example Usage:
        GET /api/dashboard/distribution-chart?blood_products=whole_blood&blood_products=platelets&blood_types=A+&from_date=2024-01-01T00:00:00Z

    Required Permissions:
    - facility.manage OR laboratory.manage OR blood.inventory.manage

    Data Structure:
    Each data point contains:
    - date: ISO timestamp for the day
    - formattedDate: Human-readable date (e.g., "Jan 15")
    - [product_type]: Quantity distributed for each selected product type
    """
    import time

    # Start performance timing
    start_time = time.time()

    # Initialize logging context with request tracking information
    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        logger.info(
            "Inventory chart request initiated",
            extra={
                "event_type": "inventory_chart_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "from_date": from_date,
                "to_date": to_date,
                "blood_products": blood_products,
                "blood_types": blood_types,
            },
        )

        try:
            blood_bank_id = await get_user_blood_bank_id(db, current_user.id)

            # Parse and validate dates
            parsed_from_date = None
            parsed_to_date = None

            if from_date:
                try:
                    parsed_from_date = datetime.fromisoformat(
                        from_date.replace("Z", "+00:00")
                    )
                except ValueError:
                    logger.warning(
                        "Invalid from_date format provided",
                        extra={
                            "event_type": "invalid_from_date",
                            "user_id": str(current_user.id),
                            "from_date": from_date,
                        },
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid from_date format. Use ISO 8601 format (e.g., '2024-01-15T00:00:00Z')",
                    )

            if to_date:
                try:
                    parsed_to_date = datetime.fromisoformat(
                        to_date.replace("Z", "+00:00")
                    )
                except ValueError:
                    logger.warning(
                        "Invalid to_date format provided",
                        extra={
                            "event_type": "invalid_to_date",
                            "user_id": str(current_user.id),
                            "to_date": to_date,
                        },
                    )
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid to_date format. Use ISO 8601 format (e.g., '2024-01-15T23:59:59Z')",
                    )

            # Validate date range
            if (
                parsed_from_date
                and parsed_to_date
                and parsed_from_date > parsed_to_date
            ):
                logger.warning(
                    "Invalid date range - from_date after to_date",
                    extra={
                        "event_type": "invalid_date_range",
                        "user_id": str(current_user.id),
                        "from_date": from_date,
                        "to_date": to_date,
                    },
                )
                raise HTTPException(
                    status_code=400,
                    detail="The 'from' date cannot be after the 'to' date",
                )

            # Validate date range size (max 365 days)
            if parsed_from_date and parsed_to_date:
                days_diff = (parsed_to_date - parsed_from_date).days
                if days_diff > 365:
                    logger.warning(
                        "Date range too large",
                        extra={
                            "event_type": "date_range_too_large",
                            "user_id": str(current_user.id),
                            "days_diff": days_diff,
                        },
                    )
                    raise HTTPException(
                        status_code=400, detail="Date range cannot exceed 365 days"
                    )

            # Validate blood products
            valid_products = [
                BloodProduct.WHOLE_BLOOD,
                BloodProduct.RED_BLOOD_CELLS,
                BloodProduct.PLATELETS,
                BloodProduct.FRESH_FROZEN_PLASMA,
                BloodProduct.CRYOPRECIPITATE,
                BloodProduct.ALBUMIN,
                BloodProduct.PLASMA,
            ]

            if blood_products:
                invalid_products = [
                    p for p in blood_products if p not in valid_products
                ]
                if invalid_products:
                    logger.warning(
                        "Invalid blood product types provided",
                        extra={
                            "event_type": "invalid_blood_products",
                            "user_id": str(current_user.id),
                            "invalid_products": invalid_products,
                        },
                    )
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid blood product types: {invalid_products}. Valid options: {[p.value for p in valid_products]}",
                    )

            # Validate blood types
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

            if blood_types:
                invalid_blood_types = [
                    bt for bt in blood_types if bt not in valid_blood_types
                ]
                if invalid_blood_types:
                    logger.warning(
                        "Invalid blood types provided",
                        extra={
                            "event_type": "invalid_blood_types",
                            "user_id": str(current_user.id),
                            "invalid_blood_types": invalid_blood_types,
                        },
                    )
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid blood types: {invalid_blood_types}. Valid options: {[bt.value for bt in valid_blood_types]}",
                    )

            stats_service = StatsService(db)

            logger.debug(
                "Fetching inventory chart data",
                extra={
                    "event_type": "inventory_chart_fetch",
                    "facility_id": str(blood_bank_id),
                    "user_id": str(current_user.id),
                    "from_date": from_date,
                    "to_date": to_date,
                    "blood_products": blood_products,
                    "blood_types": blood_types,
                },
            )

            # Get chart data with selected products and blood types
            chart_data = await stats_service.get_distribution_chart_data(
                blood_bank_id=blood_bank_id,
                from_date=parsed_from_date,
                to_date=parsed_to_date,
                selected_blood_products=blood_products,  # Pass enum objects directly
                selected_blood_types=blood_types,
            )

            # Set actual date range used (with defaults applied)
            actual_to_date = parsed_to_date or datetime.now()
            actual_from_date = parsed_from_date or (actual_to_date - timedelta(days=7))

            # Set blood products used (with defaults applied)
            actual_blood_products = blood_products or [
                "whole_blood",
                "red_blood_cells",
                "platelets",
            ]
            actual_blood_types = blood_types

            # Create metadata
            metadata = ChartMetadata(
                totalRecords=len(chart_data),
                dateRange={
                    "from": actual_from_date.isoformat(),
                    "to": actual_to_date.isoformat(),
                },
                bloodProducts=actual_blood_products,
                bloodTypes=actual_blood_types,
            )

            # Log performance metric
            execution_time = time.time() - start_time
            log_performance_metric(
                operation="inventory_chart",
                duration_seconds=execution_time,
                additional_metrics={
                    "blood_bank_id": str(blood_bank_id),
                    "user_id": str(current_user.id),
                    "data_points": len(chart_data),
                    "date_range_days": (actual_to_date - actual_from_date).days,
                    "selected_products_count": len(actual_blood_products),
                    "selected_blood_types_count": (
                        len(actual_blood_types) if actual_blood_types else 0
                    ),
                },
            )

            logger.info(
                "Inventory chart data retrieved successfully",
                extra={
                    "event_type": "inventory_chart_success",
                    "user_id": str(current_user.id),
                    "blood_bank_id": str(blood_bank_id),
                    "execution_time_seconds": round(execution_time, 4),
                    "data_points": len(chart_data),
                    "date_range_days": (actual_to_date - actual_from_date).days,
                    "selected_products": actual_blood_products,
                    "selected_blood_types": actual_blood_types,
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
                "Inventory chart data retrieval failed",
                extra={
                    "event_type": "inventory_chart_failed",
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
# BLOOD REQUEST CHART ENDPOINT
# =============================================================================
# Provides time-series data for blood request visualization and analytics.
# Supports filtering by date range, blood products, blood types, and request
# direction (sent/received). Includes caching for performance optimization.
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
    """
    Get blood request chart data optimized for performance.

    This endpoint provides time-series data for blood request analytics with
    comprehensive filtering options. The data shows daily request volumes
    aggregated by product type and blood type.

    Features:
    - Automatic caching for performance (5-minute TTL)
    - Request timeout protection (30 seconds)
    - Comprehensive filtering options
    - Performance monitoring and logging

    Query Parameters:
    - from_date: Start date as datetime object (optional, defaults to 7 days ago)
    - to_date: End date as datetime object (optional, defaults to now)
    - blood_products: List of blood product types to include (optional)
      Available: whole_blood, red_blood_cells, platelets, fresh_frozen_plasma,
                 cryoprecipitate, albumin
    - blood_types: List of blood types to filter by (optional)
      Available: A+, A-, B+, B-, AB+, AB-, O+, O-
    - request_direction: Filter requests by direction (optional)
      Options: "sent" (requests made by facility),
               "received" (requests fulfilled by facility),
               null (both directions)

    Returns:
        RequestChartResponse: Time-series data with metadata and caching info

    Required Permissions:
    - facility.manage OR laboratory.manage OR blood.inventory.manage

    Cache Strategy:
    - Results cached for 5 minutes based on parameters
    - Cache key includes all filter parameters for accuracy
    - Cache hits are logged for monitoring

    Performance:
    - 30-second timeout to prevent hanging requests
    - Comprehensive performance metrics logging
    - Date range limited to 365 days maximum
    """

    # Start performance timing
    start_time = time.time()

    # Set up logging context with request tracking
    with LogContext(
        req_id=getattr(request.state, "request_id", None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, "session_id", None) if request else None,
    ):
        # Log the initiation of the request chart data request
        logger.info(
            "Request chart data request initiated",
            extra={
                "event_type": "request_chart_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
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
            # Extract facility ID from the current user's profile
            # This determines which facility's request data to retrieve
            facility_id = get_user_facility_id(current_user)

            # VALIDATION SECTION
            # =================

            # Validate that from_date is before to_date
            if from_date and to_date and from_date >= to_date:
                logger.warning(
                    "Invalid date range provided",
                    extra={
                        "event_type": "invalid_date_range",
                        "user_id": str(current_user.id),
                        "from_date": from_date.isoformat(),
                        "to_date": to_date.isoformat(),
                    },
                )
                raise HTTPException(
                    status_code=400, detail="from_date must be before to_date"
                )

            # Validate that date range doesn't exceed maximum allowed (365 days)
            # This prevents performance issues and excessive data retrieval
            if from_date and to_date:
                days_diff = (to_date - from_date).days
                if days_diff > 365:
                    logger.warning(
                        "Date range too large",
                        extra={
                            "event_type": "date_range_too_large",
                            "user_id": str(current_user.id),
                            "days_diff": days_diff,
                        },
                    )
                    raise HTTPException(
                        status_code=400, detail="Date range cannot exceed 365 days"
                    )

            # CACHING SECTION
            # ===============

            # Generate a unique cache key based on all request parameters
            # This ensures cached results are specific to the exact query
            cache_key_str = cache_key(
                "request_chart",  # Cache namespace
                facility_id,  # Facility-specific caching
                from_date.isoformat() if from_date else None,
                to_date.isoformat() if to_date else None,
                tuple(bp.value for bp in blood_products) if blood_products else None,
                tuple(bt.value for bt in blood_types) if blood_types else None,
                request_direction.value if request_direction else None,
            )

            # Attempt to retrieve cached result first for performance
            cached_result = manual_cache_get(cache_key_str)
            if cached_result:
                # Return cached data immediately with performance logging
                logger.info(
                    "Request chart data returned from cache",
                    extra={
                        "event_type": "request_chart_cache_hit",
                        "user_id": str(current_user.id),
                        "facility_id": str(facility_id),
                        "execution_time_seconds": round(time.time() - start_time, 4),
                        "data_points": (
                            len(cached_result.data)
                            if hasattr(cached_result, "data")
                            else 0
                        ),
                    },
                )
                return cached_result

            # DATA RETRIEVAL SECTION
            # ======================

            # Log that we're fetching fresh data from the database
            logger.debug(
                "Fetching request chart data from database",
                extra={
                    "event_type": "request_chart_fetch",
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                    "cache_key": (
                        cache_key_str[:50]
                        + "..."  # Truncate long cache keys for logging
                        if len(cache_key_str) > 50
                        else cache_key_str
                    ),
                },
            )

            # Execute the data retrieval with timeout protection
            # This prevents requests from hanging indefinitely
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
                timeout=30.0,  # 30-second timeout
            )

            # RESPONSE BUILDING SECTION
            # =========================

            # Ensure we have valid dates for metadata even if parameters were None
            # Default to a 7-day window ending today
            actual_from_date = from_date or (datetime.now() - timedelta(days=7))
            actual_to_date = to_date or datetime.now()

            # Build metadata for the response including record count and date range
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

            # Cache the result for 5 minutes
            manual_cache_set(cache_key_str, response, ttl=300)

            # Log performance metric
            execution_time = time.time() - start_time
            log_performance_metric(
                operation="request_chart",
                duration_seconds=execution_time,
                additional_metrics={
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                    "data_points": len(chart_data),
                    "date_range_days": (
                        (to_date - from_date).days if from_date and to_date else None
                    ),
                    "blood_products_count": (
                        len(blood_products) if blood_products else 0
                    ),
                    "blood_types_count": len(blood_types) if blood_types else 0,
                    "request_direction": (
                        request_direction.value if request_direction else None
                    ),
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
                    "date_range_days": (
                        (to_date - from_date).days if from_date and to_date else None
                    ),
                    "blood_products": (
                        [bp.value for bp in blood_products] if blood_products else None
                    ),
                    "blood_types": (
                        [bt.value for bt in blood_types] if blood_types else None
                    ),
                    "request_direction": (
                        request_direction.value if request_direction else None
                    ),
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
                    "facility_id": (
                        str(facility_id) if "facility_id" in locals() else "unknown"
                    ),
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
                    "facility_id": (
                        str(facility_id) if "facility_id" in locals() else "unknown"
                    ),
                    "execution_time_seconds": round(execution_time, 4),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )


# =============================================================================
# MODULE SUMMARY
# =============================================================================
# This stats_routes.py module provides a comprehensive REST API for blood bank
# dashboard statistics and analytics. It includes the following key endpoints:
#
# ENDPOINTS OVERVIEW:
# ------------------
# 1. /dashboard/summary
#    - Provides high-level daily comparison statistics
#    - Shows today vs yesterday for stock, transfers, requests
#    - Includes percentage changes and trend directions
#
# 2. /dashboard/monthly-transfers
#    - Monthly aggregated transfer statistics
#    - Supports year and blood product filtering
#    - Returns complete 12-month dataset
#
# 3. /dashboard/blood-product-breakdown
#    - Breakdown of transfers by blood product type
#    - Supports year/month filtering
#    - Shows both unit counts and transfer counts
#
# 4. /dashboard/transfer-trends
#    - Daily transfer trends over configurable periods
#    - Default 30-day lookback period
#    - Useful for identifying patterns and anomalies
#
# 5. /dashboard/distribution-chart
#    - Time-series distribution data for charts
#    - Supports comprehensive filtering options
#    - Optimized for dashboard visualization
#
# 6. /dashboard/request-chart
#    - Time-series request data with caching
#    - Supports sent/received request filtering
#    - Includes timeout protection and performance monitoring
#
# COMMON FEATURES:
# ---------------
# - Permission-based access control
# - Comprehensive logging and performance monitoring
# - Input validation and error handling
# - Consistent response formats
# - Database session management
# - User context tracking
#
# SECURITY:
# ---------
# - All endpoints require specific permissions
# - User facility isolation (users only see their facility's data)
# - Request parameter validation
# - SQL injection protection via SQLAlchemy ORM
#
# PERFORMANCE:
# -----------
# - Strategic caching for heavy operations
# - Query timeout protection
# - Performance metrics logging
# - Date range limitations to prevent abuse
# - Efficient database queries with proper indexing considerations
#
# ERROR HANDLING:
# --------------
# - Structured error responses
# - Comprehensive error logging
# - Graceful degradation for edge cases
# - Clear error messages for API consumers
#
# MONITORING:
# ----------
# - Request/response logging
# - Performance metrics
# - Cache hit/miss tracking
# - Error rate monitoring
# - User activity tracking
# =============================================================================
