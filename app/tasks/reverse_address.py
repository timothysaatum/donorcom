import asyncio
import logging
from typing import List
from app.models.health_facility_model import Facility
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.executors.asyncio import AsyncIOExecutor
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import async_session

logger = logging.getLogger("facility_gps")
logger.setLevel(logging.INFO)

# Global scheduler instance
scheduler = None

# GhanaPost GPS API endpoint
GPS_API_URL = "https://ghanapostgps.sperixlabs.org/get-location"
HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}

# Max concurrent requests to GhanaPost API
MAX_CONCURRENT_REQUESTS = 10

# Batch size for database updates
BATCH_SIZE = 50


async def fetch_coordinates(digital_address: str) -> dict:
    """Fetch latitude and longitude from GhanaPost GPS API."""
    payload = {"address": digital_address}
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(GPS_API_URL, data=payload, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json().get("data", {}).get("Table", [{}])[0]
            lat = data.get("CenterLatitude")
            lon = data.get("CenterLongitude")
            if lat is not None and lon is not None:
                return {"latitude": float(lat), "longitude": float(lon)}
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            logger.error(f"Failed to fetch GPS for {digital_address}: {e}")
    return {}


async def update_facility_coordinates(facility: Facility, session: AsyncSession):
    """Update a single facility with latitude and longitude."""
    coords = await fetch_coordinates(facility.facility_digital_address)
    if coords:
        facility.latitude = coords["latitude"]
        facility.longitude = coords["longitude"]
        session.add(facility)
        logger.info(f"Updated Facility {facility.id} with coordinates {coords}")


async def process_facilities_batch(facilities: List[Facility]):
    """Process a batch of facilities concurrently."""
    async with async_session() as session:
        tasks = []
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        async def sem_task(fac):
            async with semaphore:
                await update_facility_coordinates(fac, session)

        for facility in facilities:
            tasks.append(asyncio.create_task(sem_task(facility)))

        await asyncio.gather(*tasks)
        await session.commit()


async def fetch_and_update_facilities():
    """Fetch all facilities with null coordinates and update them."""
    try:
        async with async_session() as session:
            result = await session.execute(
                select(Facility).where(Facility.latitude.is_(None), Facility.longitude.is_(None))
            )
            facilities = result.scalars().all()

        if not facilities:
            logger.info("No facilities with missing coordinates found.")
            return

        # Process in batches
        for i in range(0, len(facilities), BATCH_SIZE):
            batch = facilities[i:i + BATCH_SIZE]
            await process_facilities_batch(batch)
            
        logger.info(f"Processed {len(facilities)} facilities for coordinate updates")
    except Exception as e:
        logger.error(f"Error updating facility coordinates: {e}")


async def scheduled_task():
    """The main scheduled task - this runs every 5 minutes"""
    logger.info("Starting facility coordinate update task...")
    await fetch_and_update_facilities()
    logger.info("Facility coordinate update task completed")


def start_periodic_task():
    """Start the periodic facility coordinate updater"""
    global scheduler
    
    if scheduler is not None:
        logger.info("Periodic task scheduler already running")
        return
    
    scheduler = AsyncIOScheduler(
        executors={'default': AsyncIOExecutor()},
        job_defaults={
            'coalesce': False, 
            'max_instances': 1,
            'misfire_grace_time': 30
        }
    )
    
    scheduler.add_job(
        scheduled_task,
        "interval", 
        minutes=5,
        id='facility_coordinates_job',
        replace_existing=True
    )
    
    try:
        scheduler.start()
        logger.info("Started periodic facility coordinate updater")
    except Exception as e:
        logger.error(f"Error starting periodic task scheduler: {e}")


def stop_periodic_task():
    """Stop the periodic task scheduler gracefully"""
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=True)
        scheduler = None
        logger.info("Periodic facility coordinate updater stopped")