from app.utils.permission_checker import require_permission
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import date, timedelta

from app.dependencies import get_db
from app.schemas.stats_schema import (
    BloodProductType,
    DashboardSummaryResponse, 
    MonthlyTransferStatsResponse,
    BloodProductBreakdownResponse,
    TransferTrendsResponse
)
from app.services.stats_service import StatsService
from app.models.user import User
from app.utils.logging_config import get_logger, log_performance_metric, LogContext

# Initialize logger
logger = get_logger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

def get_user_facility_id(current_user: User) -> str:
    """
    Extract facility ID based on user role - handles edge cases.
    Priority: facility_administrator > lab_manager > staff
    """
    user_facility_id = None
    user_role_names = {role.name for role in current_user.roles}  # Use set for faster lookup
    
    logger.debug(
        "Extracting facility ID for user",
        extra={
            "event_type": "facility_id_extraction",
            "user_id": str(current_user.id),
            "user_roles": list(user_role_names),
            "user_email": current_user.email
        }
    )
    
    # Check roles in priority order
    if "facility_administrator" in user_role_names:
        user_facility_id = current_user.facility.id if current_user.facility else None
        if not user_facility_id:
            logger.error(
                "Facility administrator without associated facility",
                extra={
                    "event_type": "facility_admin_missing_facility",
                    "user_id": str(current_user.id),
                    "user_email": current_user.email
                }
            )
            raise HTTPException(
                status_code=400, 
                detail="Facility administrator must be associated with a facility"
            )
    
    elif user_role_names & {"lab_manager", "staff"}:  # Intersection check
        user_facility_id = current_user.work_facility_id
        if not user_facility_id:
            logger.error(
                "Staff/lab manager without work facility",
                extra={
                    "event_type": "staff_missing_work_facility",
                    "user_id": str(current_user.id),
                    "user_email": current_user.email,
                    "user_roles": list(user_role_names)
                }
            )
            raise HTTPException(
                status_code=400, 
                detail="Staff and lab managers must be associated with a work facility"
            )
    
    else:
        # User has roles but none that give facility access
        logger.warning(
            "User roles do not provide facility access",
            extra={
                "event_type": "insufficient_facility_access",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "user_roles": list(user_role_names)
            }
        )
        raise HTTPException(
            status_code=403, 
            detail=f"User roles {list(user_role_names)} do not provide facility access"
        )
    
    logger.debug(
        "Facility ID extracted successfully",
        extra={
            "event_type": "facility_id_extracted",
            "user_id": str(current_user.id),
            "facility_id": str(user_facility_id),
            "primary_role": next(iter(user_role_names & {"facility_administrator", "lab_manager", "staff"}), "unknown")
        }
    )
    
    return user_facility_id


@router.get("/summary", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    )),
    request: Request = None
):
    """
    Get dashboard summary for a facility.
    - Total in stock, Total transferred, & Total requested
    - Shape: {
        "total_in_stock": {
            "value": 0,
            "change": 0,
            "direction": "string"
        },
        "total_transferred": {
            "value": 0,
            "change": 0,
            "direction": "string"
        },
        "total_transferred": {
            "value": 0,
            "change": 0,
            "direction": "string"
        },
        "total_requested": {
            "value": 0,
            "change": 0,
            "direction": "string"
        }
    }
    """
    import time
    start_time = time.time()
    
    with LogContext(
        req_id=getattr(request.state, 'request_id', None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, 'session_id', None) if request else None
    ):
        logger.info(
            "Dashboard summary request initiated",
            extra={
                "event_type": "dashboard_summary_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email
            }
        )
        
        try:
            facility_id = get_user_facility_id(current_user)
            stats_service = StatsService(db)
            
            logger.debug(
                "Fetching dashboard summary data",
                extra={
                    "event_type": "dashboard_summary_fetch",
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id)
                }
            )
            
            data = await stats_service.get_dashboard_summary(facility_id)
            
            # Log performance metric
            execution_time = time.time() - start_time
            log_performance_metric(
                operation="dashboard_summary",
                duration_seconds=execution_time,
                additional_metrics={
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id)
                }
            )
            
            logger.info(
                "Dashboard summary retrieved successfully",
                extra={
                    "event_type": "dashboard_summary_success",
                    "user_id": str(current_user.id),
                    "facility_id": str(facility_id),
                    "execution_time_seconds": round(execution_time, 4),
                    "total_in_stock": data.total_in_stock.value if data and data.total_in_stock else 0,
                    "total_transferred": data.total_transferred.value if data and data.total_transferred else 0,
                    "total_requested": data.total_requested.value if data and data.total_requested else 0
                }
            )
            
            return data
            
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
                    "error": str(e)
                },
                exc_info=True
            )
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/monthly-transfers", response_model=MonthlyTransferStatsResponse)
async def monthly_transfer_stats(
    year: Optional[int] = Query(None, description="Year to get statistics for (defaults to current year)"),
    blood_product_types: Optional[List[BloodProductType]] = Query(None, description="Filter by specific blood product types"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    )),
    request: Request = None
):
    """
    Get monthly blood transfer statistics for the current user's facility.

    Provide data for representation on the dashboard graph.
    """
    import time
    start_time = time.time()
    
    with LogContext(
        req_id=getattr(request.state, 'request_id', None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, 'session_id', None) if request else None
    ):
        # Default to current year if not provided
        if year is None:
            year = date.today().year
            
        logger.info(
            "Monthly transfer stats request initiated",
            extra={
                "event_type": "monthly_transfer_stats_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "requested_year": year,
                "blood_product_types": blood_product_types
            }
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
                        "valid_range": f"2000-{current_year + 1}"
                    }
                )
                raise HTTPException(
                    status_code=400, 
                    detail=f"Year must be between 2000 and {current_year + 1}"
                )
            
            stats_service = StatsService(db)
            
            logger.debug(
                "Fetching monthly transfer statistics",
                extra={
                    "event_type": "monthly_transfer_stats_fetch",
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                    "year": year,
                    "blood_product_types": blood_product_types
                }
            )
            
            monthly_data = await stats_service.get_monthly_transfer_stats(
                facility_id=facility_id,
                year=year,
                blood_product_types=blood_product_types
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
                    "total_units_year": total_units_year
                }
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
                    "blood_product_types": blood_product_types
                }
            )
            
            return MonthlyTransferStatsResponse(
                data=monthly_data,
                total_units_year=total_units_year,
                facility_id=facility_id,
                year=year,
                blood_product_types=blood_product_types
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
                    "error": str(e)
                },
                exc_info=True
            )
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/blood-product-breakdown", response_model=BloodProductBreakdownResponse)
async def blood_product_breakdown(
    year: Optional[int] = Query(None, description="Year to get statistics for (defaults to current year)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Optional month filter (1-12)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    )),
    request: Request = None
):
    """
    Breakdown of blood transfers by product type for the current user's facility.
    
    Provides insights into which blood products are most frequently transferred.
    """
    import time
    start_time = time.time()
    
    with LogContext(
        req_id=getattr(request.state, 'request_id', None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, 'session_id', None) if request else None
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
                "requested_month": month
            }
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
                        "valid_range": f"2024-{current_year + 1}"
                    }
                )
                raise HTTPException(
                    status_code=400, 
                    detail=f"Year must be between 2024 and {current_year + 1}"
                )
            
            # Validate month if provided
            if month is not None and (month < 1 or month > 12):
                logger.warning(
                    "Invalid month parameter provided",
                    extra={
                        "event_type": "invalid_month_parameter",
                        "user_id": str(current_user.id),
                        "requested_month": month
                    }
                )
                raise HTTPException(
                    status_code=400,
                    detail="Month must be between 1 and 12"
                )
            
            stats_service = StatsService(db)
            
            logger.debug(
                "Fetching blood product breakdown data",
                extra={
                    "event_type": "blood_product_breakdown_fetch",
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                    "year": year,
                    "month": month
                }
            )
            
            breakdown_data = await stats_service.get_blood_product_breakdown(
                facility_id=facility_id,
                year=year,
                month=month
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
                    "breakdown_items": len(breakdown_data) if breakdown_data else 0
                }
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
                    "breakdown_items": len(breakdown_data) if breakdown_data else 0
                }
            )
            
            return BloodProductBreakdownResponse(
                data=breakdown_data,
                facility_id=facility_id,
                year=year,
                month=month
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
                    "error": str(e)
                },
                exc_info=True
            )
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/transfer-trends", response_model=TransferTrendsResponse)
async def transfer_trends(
    days: int = Query(30, ge=1, le=365, description="Number of days to include in the trend (1-365)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(
        "facility.manage",
        "laboratory.manage",
        "blood.inventory.can_view"
    )),
    request: Request = None
):
    """
    Daily transfer trends for the current user's facility over the last N days.
    
    Useful for creating short-term trend analysis and identifying patterns.
    """
    import time
    start_time = time.time()
    
    with LogContext(
        req_id=getattr(request.state, 'request_id', None) if request else None,
        usr_id=str(current_user.id),
        sess_id=getattr(request.state, 'session_id', None) if request else None
    ):
        logger.info(
            "Transfer trends request initiated",
            extra={
                "event_type": "transfer_trends_started",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "requested_days": days
            }
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
                        "requested_days": days
                    }
                )
                raise HTTPException(
                    status_code=400,
                    detail="Days must be between 1 and 365"
                )
            
            stats_service = StatsService(db)
            
            logger.debug(
                "Fetching transfer trends data",
                extra={
                    "event_type": "transfer_trends_fetch",
                    "facility_id": str(facility_id),
                    "user_id": str(current_user.id),
                    "days": days
                }
            )
            
            trends_data = await stats_service.get_transfer_trends(
                facility_id=facility_id,
                days=days
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
                    "trend_data_points": len(trends_data) if trends_data else 0
                }
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
                    "trend_data_points": len(trends_data) if trends_data else 0
                }
            )
            
            return TransferTrendsResponse(
                data=trends_data,
                facility_id=facility_id,
                days=days,
                period_start=start_date.isoformat(),
                period_end=end_date.isoformat()
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
                    "error": str(e)
                },
                exc_info=True
            )
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")