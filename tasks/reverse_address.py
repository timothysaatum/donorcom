import asyncio
import logging
from typing import List
from app.models.health_facility import Facility
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as async_engine

logger = logging.getLogger("facility_gps")
logger.setLevel(logging.INFO)

# Async session factory
AsyncSessionLocal = sessionmaker(
    bind=async_engine, class_=AsyncSession, expire_on_commit=False
)

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
    async with AsyncSessionLocal() as session:
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
    async with AsyncSessionLocal() as session:
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


async def scheduled_task():
    await fetch_and_update_facilities()

def start_periodic_task():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: asyncio.create_task(scheduled_task()), "interval", minutes=5)
    scheduler.start()
    logger.info("Started periodic facility coordinate updater.")
