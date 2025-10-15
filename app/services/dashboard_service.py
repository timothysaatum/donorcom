"""
Dashboard Service - Real-time dashboard metrics calculation
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date, timedelta
from uuid import UUID
from typing import Dict, Any
from app.models.inventory_model import BloodInventory
from app.models.distribution_model import BloodDistribution
from app.models.request_model import BloodRequest, DashboardDailySummary
from app.utils.logging_config import get_logger
from app.database import async_session

logger = get_logger(__name__)


async def refresh_facility_dashboard_metrics(
    session: AsyncSession, facility_id: UUID, today: date = None
) -> None:
    """
    Immediately refresh dashboard metrics for a single facility.
    Call this after creating requests, adding inventory, or issuing blood.

    Args:
        session: Active database session
        facility_id: The facility to refresh metrics for
        today: The date to refresh (defaults to today)
    """
    if today is None:
        today = date.today()

    logger.info(f"Refreshing dashboard metrics for facility {facility_id}")

    try:
        # --- Stock ---
        stock_query = (
            select(func.coalesce(func.sum(BloodInventory.quantity), 0))
            .join(BloodInventory.blood_bank)
            .where(BloodInventory.blood_bank.has(facility_id=facility_id))
        )
        total_stock = (await session.execute(stock_query)).scalar_one()

        # --- Transferred (delivered today) ---
        # Count blood delivered TO this facility (incoming blood)
        # Note: Using func.date() instead of cast() for SQLite compatibility
        transferred_query = select(
            func.coalesce(func.sum(BloodDistribution.quantity), 0)
        ).where(
            BloodDistribution.dispatched_to_id == facility_id,
            BloodDistribution.date_delivered.is_not(None),
            func.date(BloodDistribution.date_delivered) == today,
        )
        total_transferred = (await session.execute(transferred_query)).scalar_one()

        # --- Requests (created today) ---
        # Count requests received BY this facility (facility_id)
        # This represents incoming blood requests to this facility
        # Note: Using func.date() instead of cast() for SQLite compatibility
        requests_query = select(func.count(BloodRequest.id)).where(
            BloodRequest.facility_id == facility_id,
            func.date(BloodRequest.created_at) == today,
        )
        total_requests = (await session.execute(requests_query)).scalar_one()

        # --- Upsert into DashboardDailySummary ---
        existing = await session.execute(
            select(DashboardDailySummary).where(
                DashboardDailySummary.facility_id == facility_id,
                DashboardDailySummary.date == today,
            )
        )
        existing_summary = existing.scalar_one_or_none()

        if existing_summary:
            existing_summary.total_stock = total_stock
            existing_summary.total_transferred = total_transferred
            existing_summary.total_requests = total_requests
            logger.info(
                f"Updated dashboard metrics for facility {facility_id}: "
                f"stock={total_stock}, transferred={total_transferred}, requests={total_requests}"
            )
        else:
            summary = DashboardDailySummary(
                facility_id=facility_id,
                date=today,
                total_stock=total_stock,
                total_transferred=total_transferred,
                total_requests=total_requests,
            )
            session.add(summary)
            logger.info(
                f"Created dashboard metrics for facility {facility_id}: "
                f"stock={total_stock}, transferred={total_transferred}, requests={total_requests}"
            )

        await session.commit()
        logger.info(
            f"Dashboard metrics refreshed successfully for facility {facility_id}"
        )

    except Exception as e:
        logger.error(
            f"Error refreshing dashboard metrics for facility {facility_id}: {str(e)}"
        )
        await session.rollback()
        # Don't raise - dashboard refresh failures shouldn't block main operations


async def get_realtime_dashboard_summary(
    session: AsyncSession, facility_id: UUID
) -> Dict[str, Any]:
    """
    Get dashboard summary with REAL-TIME data (not cached).
    Shows cumulative stats for the last 7 days.

    Returns the same format as StatsService.get_dashboard_summary()
    """
    today = date.today()
    seven_days_ago = today - timedelta(days=7)

    # Calculate real-time metrics
    # Stock (current total, not time-bound)
    stock_query = (
        select(func.coalesce(func.sum(BloodInventory.quantity), 0))
        .join(BloodInventory.blood_bank)
        .where(BloodInventory.blood_bank.has(facility_id=facility_id))
    )
    total_stock = (await session.execute(stock_query)).scalar_one()

    # Transferred in last 7 days
    # Note: Using func.date() instead of cast() for SQLite compatibility
    transferred_query = select(
        func.coalesce(func.sum(BloodDistribution.quantity), 0)
    ).where(
        BloodDistribution.dispatched_to_id == facility_id,
        BloodDistribution.date_delivered.is_not(None),
        func.date(BloodDistribution.date_delivered) >= seven_days_ago,
    )
    total_transferred = (await session.execute(transferred_query)).scalar_one()

    # Requests in last 7 days - count requests received BY this facility
    # Note: Using func.date() instead of cast() for SQLite compatibility
    requests_query = select(func.count(BloodRequest.id)).where(
        BloodRequest.facility_id == facility_id,
        func.date(BloodRequest.created_at) >= seven_days_ago,
    )
    total_requests = (await session.execute(requests_query)).scalar_one()

    # Return in the same format as cached version
    return {
        "stock": {"value": total_stock, "change": 0.0, "direction": "neutral"},
        "transferred": {
            "value": total_transferred,
            "change": 0.0,
            "direction": "neutral",
        },
        "requests": {"value": total_requests, "change": 0.0, "direction": "neutral"},
    }


async def async_refresh_facility_dashboard_metrics(
    facility_id: UUID, today: date = None
) -> None:
    """
    Non-blocking wrapper to refresh dashboard metrics using an independent DB session.
    Use this from request/distribution handlers to update the cached DashboardDailySummary
    without holding or re-using the caller's DB session.
    """
    try:
        async with async_session() as session:
            await refresh_facility_dashboard_metrics(session, facility_id, today)
    except Exception as e:
        # Log and continue - dashboard refresh must not crash caller
        logger.warning(
            f"async_refresh_facility_dashboard_metrics failed for {facility_id}: {e}"
        )
