from app.models.health_facility import Facility
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.executors.asyncio import AsyncIOExecutor
from sqlalchemy import select, func, cast, Date
from datetime import date
from app.database import async_session as async_sessionmaker
from app.models.inventory import BloodInventory
from app.models.distribution import BloodDistribution
from app.models.request import BloodRequest, DashboardDailySummary

# Global scheduler instance
scheduler = None

async def refresh_dashboard_metrics():
    """
    Compute metrics for all facilities and store them in DashboardDailySummary.
    Runs every 5 minutes.
    """
    print("Refreshing dashboard metrics...")
    try:
        async with async_sessionmaker() as session:  # open async db session
            today = date.today()

            # get all facility IDs using ORM
            result = await session.execute(select(Facility.id))
            facility_ids = [row[0] for row in result.all()]

            for fid in facility_ids:
                # --- Stock ---
                stock_query = select(func.coalesce(func.sum(BloodInventory.quantity), 0)).join(
                    BloodInventory.blood_bank
                ).where(BloodInventory.blood_bank.has(facility_id=fid))
                total_stock = (await session.execute(stock_query)).scalar_one()

                # --- Transferred (delivered today) ---
                transferred_query = select(func.coalesce(func.sum(BloodDistribution.quantity), 0)).where(
                    BloodDistribution.dispatched_to_id == fid,
                    BloodDistribution.date_delivered.is_not(None),
                    cast(BloodDistribution.date_delivered, Date) == today
                )
                total_transferred = (await session.execute(transferred_query)).scalar_one()

                # --- Requests (today) ---
                requests_query = select(func.count(BloodRequest.id)).where(
                    BloodRequest.facility_id == fid,
                    cast(BloodRequest.created_at, Date) == today
                )
                total_requests = (await session.execute(requests_query)).scalar_one()

                # --- Upsert into DashboardDailySummary ---
                existing = await session.execute(
                    select(DashboardDailySummary).where(
                        DashboardDailySummary.facility_id == fid,
                        DashboardDailySummary.date == today,
                    )
                )
                existing_summary = existing.scalar_one_or_none()

                if existing_summary:
                    existing_summary.total_stock = total_stock
                    existing_summary.total_transferred = total_transferred
                    existing_summary.total_requests = total_requests
                else:
                    summary = DashboardDailySummary(
                        facility_id=fid,
                        date=today,
                        total_stock=total_stock,
                        total_transferred=total_transferred,
                        total_requests=total_requests,
                    )
                    session.add(summary)

            await session.commit()
        print("Dashboard metrics refreshed.")
    except Exception as e:
        print(f"Error refreshing dashboard metrics: {e}")

def start_scheduler():
    """Start the dashboard metrics scheduler"""
    global scheduler
    
    if scheduler is not None:
        print("Scheduler already running")
        return
    
    scheduler = AsyncIOScheduler(
        executors={'default': AsyncIOExecutor()},
        job_defaults={
            'coalesce': False, 
            'max_instances': 1,  # Prevent multiple instances of same job
            'misfire_grace_time': 30  # Grace time for missed jobs
        }
    )
    
    scheduler.add_job(
        refresh_dashboard_metrics,
        trigger="interval",
        minutes=5,   # run every 5 minutes
        id="metrics_job",
        replace_existing=True,
    )
    
    try:
        scheduler.start()
        print("Dashboard metrics scheduler started successfully")
    except Exception as e:
        print(f"Error starting scheduler: {e}")

def stop_scheduler():
    """Stop the scheduler gracefully"""
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=True)
        scheduler = None
        print("Dashboard metrics scheduler stopped")