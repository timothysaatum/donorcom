import asyncio
from app.database import async_session
from sqlalchemy import select, func
from app.models.distribution_model import BloodDistribution
from datetime import date, timedelta


async def check():
    async with async_session() as session:
        # Get total count
        count_result = await session.execute(select(func.count(BloodDistribution.id)))
        total = count_result.scalar()
        print(f"\n=== Total distributions in DB: {total} ===\n")

        if total == 0:
            print("No distributions found in database!")
            return

        # Get recent distributions
        result = await session.execute(
            select(
                BloodDistribution.id,
                BloodDistribution.dispatched_from_id,
                BloodDistribution.dispatched_to_id,
                BloodDistribution.date_delivered,
                BloodDistribution.status,
                BloodDistribution.quantity,
                BloodDistribution.blood_product,
                BloodDistribution.created_at,
            )
            .order_by(BloodDistribution.created_at.desc())
            .limit(10)
        )
        rows = result.all()

        print(f"Recent {len(rows)} distributions:")
        print("-" * 120)
        for r in rows:
            delivered_date = r[3].date() if r[3] else "Not delivered"
            created_date = r[7].date() if r[7] else "Unknown"
            print(
                f"ID: {str(r[0])[:8]}... | From: {str(r[1])[:8]}... | To: {str(r[2])[:8]}..."
            )
            print(
                f"  Status: {r[4]} | Delivered: {delivered_date} | Created: {created_date}"
            )
            print(f"  Product: {r[6]} | Quantity: {r[5]}")
            print("-" * 120)

        # Check distributions with date_delivered in last 7 days
        seven_days_ago = date.today() - timedelta(days=7)
        recent_delivered = await session.execute(
            select(func.count(BloodDistribution.id)).where(
                BloodDistribution.date_delivered.is_not(None),
                func.date(BloodDistribution.date_delivered) >= seven_days_ago,
            )
        )
        recent_count = recent_delivered.scalar()
        print(f"\n=== Distributions delivered in last 7 days: {recent_count} ===")

        # Check distributions by status
        for status_val in [
            "pending_receive",
            "in transit",
            "delivered",
            "cancelled",
            "returned",
        ]:
            status_count = await session.execute(
                select(func.count(BloodDistribution.id)).where(
                    BloodDistribution.status == status_val
                )
            )
            count = status_count.scalar()
            print(f'  Status "{status_val}": {count}')


asyncio.run(check())
