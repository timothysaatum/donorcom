"""
Debug: Check the relationship between facilities and blood banks vs distributions
"""

import asyncio
from app.database import async_session
from sqlalchemy import select
from app.models.blood_bank_model import BloodBank
from app.models.distribution_model import BloodDistribution


async def debug_distribution_facility_mismatch():
    async with async_session() as session:
        # Get all blood banks
        bb_result = await session.execute(select(BloodBank))
        blood_banks = bb_result.scalars().all()

        print("🏥 BLOOD BANKS:")
        for bb in blood_banks:
            print(f"  {bb.blood_bank_name}")
            print(f"    Blood Bank ID: {str(bb.id)[:8]}...")
            print(f"    Facility ID:   {str(bb.facility_id)[:8]}...\n")

        # Get all distributions
        dist_result = await session.execute(
            select(BloodDistribution).where(BloodDistribution.status == "DELIVERED")
        )
        distributions = dist_result.scalars().all()

        print("📦 DISTRIBUTIONS:")
        for dist in distributions:
            print(f"  Distribution {str(dist.id)[:8]}...")
            print(f"    Status: {dist.status}")
            print(
                f"    Dispatched FROM (blood_bank_id): {str(dist.dispatched_from_id)[:8]}..."
            )
            print(
                f"    Dispatched TO (facility_id):     {str(dist.dispatched_to_id)[:8]}..."
            )
            print(f"    Date Delivered: {dist.date_delivered}")
            print()

        print("🔍 DASHBOARD QUERY LOGIC:")
        print("  The dashboard counts distributions WHERE:")
        print("    dispatched_from_id == facility_id  <-- ❌ THIS IS THE PROBLEM!")
        print()
        print("  But dispatched_from_id is a BLOOD BANK ID, not a FACILITY ID!")
        print("  We need to JOIN blood_banks to match blood_bank.facility_id")


asyncio.run(debug_distribution_facility_mismatch())
