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

            try:
                parsed = resp.json()
            except ValueError as e:
                logger.error(f"Invalid JSON from GPS API for {digital_address}: {e}")
                return {}

            # Support multiple possible response shapes defensively
            table = None
            if isinstance(parsed, dict):
                data_section = parsed.get("data")
                if isinstance(data_section, dict):
                    table = data_section.get("Table")
                elif isinstance(data_section, list):
                    table = data_section
                else:
                    # Fallback: maybe the root contains Table
                    table = parsed.get("Table")

            if not table or not isinstance(table, list):
                logger.warning(
                    f"Unexpected GPS API response format for {digital_address}: {parsed}"
                )
                return {}

            first = table[0] if len(table) > 0 and isinstance(table[0], dict) else None
            if not first:
                return {}

            lat = first.get("CenterLatitude")
            lon = first.get("CenterLongitude")
            if lat is not None and lon is not None:
                try:
                    return {"latitude": float(lat), "longitude": float(lon)}
                except (TypeError, ValueError):
                    logger.error(
                        f"Invalid coordinate values for {digital_address}: lat={lat}, lon={lon}"
                    )
                    return {}
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.error(f"Failed to fetch GPS for {digital_address}: {e}")
    return {}


async def update_facility_coordinates(facility: Facility, session: AsyncSession):
    """Update a single facility with latitude and longitude."""
    try:
        if not facility.facility_digital_address:
            logger.debug(f"Facility {facility.id} has no digital address, skipping")
            return

        coords = await fetch_coordinates(facility.facility_digital_address)
        if coords:
            # Update using the provided session which is expected to own this ORM instance
            facility.latitude = coords["latitude"]
            facility.longitude = coords["longitude"]
            session.add(facility)
            await session.commit()
            logger.info(f"Updated Facility {facility.id} with coordinates {coords}")
        else:
            logger.debug(f"No coordinates found for Facility {facility.id}")
    except Exception as e:
        logger.error(f"Error updating facility {facility.id}: {e}", exc_info=True)


async def process_facilities_batch(facilities: List[Facility]):
    """Process a batch of facilities concurrently."""
    tasks = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def sem_task(fac):
        async with semaphore:
            try:
                # Use a dedicated session per task to avoid sharing AsyncSession across
                # concurrent coroutines (which can lead to deadlocks/hangs)
                async with async_session() as session:
                    # Reload facility within this session
                    fac_obj = await session.get(Facility, fac.id)
                    if not fac_obj:
                        logger.warning(
                            f"Facility {fac.id} not found when processing batch"
                        )
                        return
                    await update_facility_coordinates(fac_obj, session)
            except Exception as e:
                logger.error(
                    f"Failed to process facility {getattr(fac, 'id', None)}: {e}",
                    exc_info=True,
                )

    for facility in facilities:
        tasks.append(asyncio.create_task(sem_task(facility)))

    # Allow individual task exceptions; we log them per-task above
    await asyncio.gather(*tasks, return_exceptions=True)


async def fetch_and_update_facilities():
    """Fetch all facilities with null coordinates and update them."""
    try:
        # Query only the minimal fields (id and digital address) in a short-lived session
        async with async_session() as session:
            result = await session.execute(
                select(Facility.id, Facility.facility_digital_address).where(
                    Facility.latitude.is_(None), Facility.longitude.is_(None)
                )
            )
            rows = result.all()

        facilities = []
        for row in rows:
            # row is a tuple (id, facility_digital_address)
            fid, digital = row[0], row[1]
            # Build lightweight objects with id and digital address so we can reload per-task
            f = Facility()
            try:
                setattr(f, "id", fid)
                setattr(f, "facility_digital_address", digital)
            except Exception:
                # Fallback to a simple namespace object
                class _Tmp:
                    pass

                f = _Tmp()
                f.id = fid
                f.facility_digital_address = digital
            facilities.append(f)

        if not facilities:
            logger.info("No facilities with missing coordinates found.")
            return

        # Process in batches
        for i in range(0, len(facilities), BATCH_SIZE):
            batch = facilities[i : i + BATCH_SIZE]
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
        executors={"default": AsyncIOExecutor()},
        job_defaults={"coalesce": False, "max_instances": 1, "misfire_grace_time": 30},
    )

    scheduler.add_job(
        scheduled_task,
        "interval",
        minutes=5,
        id="facility_coordinates_job",
        replace_existing=True,
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
