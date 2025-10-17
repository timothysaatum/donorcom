"""
Quick script to manually refresh the dashboard cache for all facilities.
Run this after manually updating distribution statuses in the database.
"""

import asyncio
from datetime import date
from app.database import async_session
from app.services.dashboard_service import refresh_facility_dashboard_metrics
from sqlalchemy import select
from app.models.health_facility_model import Facility


async def refresh_all_dashboards():
    """Refresh dashboard metrics for all facilities."""
    async with async_session() as session:
        # Get all facilities
        result = await session.execute(select(Facility))
        facilities = result.scalars().all()

        today = date.today()

        print(f"Refreshing dashboard cache for {len(facilities)} facilities...")
        print(f"Date: {today}\n")

        for facility in facilities:
            print(f"Refreshing: {facility.facility_name} ({str(facility.id)[:8]}...)")
            await refresh_facility_dashboard_metrics(session, facility.id, today)

        print("\n✅ All dashboards refreshed successfully!")
        print("🔄 The 'transferred' counts should now show correct values.")


if __name__ == "__main__":
    asyncio.run(refresh_all_dashboards())
