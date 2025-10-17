import asyncio
from app.database import async_session
from sqlalchemy import select, func, and_
from app.models.distribution_model import BloodDistribution
from datetime import datetime, timedelta


async def test_query():
    async with async_session() as session:
        # Test the exact query from stats_service
        to_date = datetime.now().replace(hour=23, minute=59, second=59)
        from_date = (to_date - timedelta(days=7)).replace(hour=0, minute=0, second=0)

        # Convert to naive
        from_date_naive = (
            from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
        )
        to_date_naive = to_date.replace(tzinfo=None) if to_date.tzinfo else to_date

        print(f"Date range: {from_date_naive} to {to_date_naive}\n")

        # Get all distributions first
        all_dists = await session.execute(
            select(
                BloodDistribution.id,
                BloodDistribution.dispatched_from_id,
                BloodDistribution.date_delivered,
                BloodDistribution.status,
            )
        )
        all_rows = all_dists.all()
        print(f"=== ALL {len(all_rows)} distributions ===")
        for r in all_rows:
            print(
                f"ID: {str(r[0])[:8]}..., From: {str(r[1])[:8]}..., Delivered: {r[2]}, Status: {r[3]}"
            )

        # Test with the exact conditions from stats_service
        print("\n=== Testing distribution chart conditions ===")

        # Get unique facility IDs
        facility_ids = set([r[1] for r in all_rows])
        print(
            f"Unique dispatched_from facilities: {[str(f)[:8] + '...' for f in facility_ids]}\n"
        )

        for facility_id in facility_ids:
            print(f"\nTesting for facility: {str(facility_id)[:8]}...")

            conditions = [
                BloodDistribution.dispatched_from_id == facility_id,
                BloodDistribution.date_delivered.is_not(None),
                BloodDistribution.date_delivered >= from_date_naive,
                BloodDistribution.date_delivered <= to_date_naive,
                BloodDistribution.status.in_(["delivered", "in transit"]),
            ]

            query = (
                select(
                    func.date(BloodDistribution.date_delivered).label(
                        "distribution_date"
                    ),
                    BloodDistribution.blood_product,
                    BloodDistribution.blood_type,
                    func.sum(BloodDistribution.quantity).label("daily_received"),
                )
                .where(and_(*conditions))
                .group_by(
                    func.date(BloodDistribution.date_delivered),
                    BloodDistribution.blood_product,
                    BloodDistribution.blood_type,
                )
            )

            result = await session.execute(query)
            rows = result.fetchall()

            if rows:
                print(f"  Found {len(rows)} distribution records:")
                for row in rows:
                    print(
                        f"    Date: {row[0]}, Product: {row[1]}, Type: {row[2]}, Quantity: {row[3]}"
                    )
            else:
                print(f"  No distributions found for this facility")

                # Debug: Check each condition separately
                print("\n  Debugging conditions:")

                cond1_result = await session.execute(
                    select(func.count(BloodDistribution.id)).where(
                        BloodDistribution.dispatched_from_id == facility_id
                    )
                )
                print(f"    1. dispatched_from_id match: {cond1_result.scalar()}")

                cond2_result = await session.execute(
                    select(func.count(BloodDistribution.id)).where(
                        BloodDistribution.dispatched_from_id == facility_id,
                        BloodDistribution.date_delivered.is_not(None),
                    )
                )
                print(f"    2. + date_delivered not null: {cond2_result.scalar()}")

                cond3_result = await session.execute(
                    select(func.count(BloodDistribution.id)).where(
                        BloodDistribution.dispatched_from_id == facility_id,
                        BloodDistribution.date_delivered.is_not(None),
                        BloodDistribution.date_delivered >= from_date_naive,
                    )
                )
                print(f"    3. + date >= from_date: {cond3_result.scalar()}")

                cond4_result = await session.execute(
                    select(func.count(BloodDistribution.id)).where(
                        BloodDistribution.dispatched_from_id == facility_id,
                        BloodDistribution.date_delivered.is_not(None),
                        BloodDistribution.date_delivered >= from_date_naive,
                        BloodDistribution.date_delivered <= to_date_naive,
                    )
                )
                print(f"    4. + date <= to_date: {cond4_result.scalar()}")

                cond5_result = await session.execute(
                    select(func.count(BloodDistribution.id)).where(
                        BloodDistribution.dispatched_from_id == facility_id,
                        BloodDistribution.date_delivered.is_not(None),
                        BloodDistribution.date_delivered >= from_date_naive,
                        BloodDistribution.date_delivered <= to_date_naive,
                        BloodDistribution.status.in_(["delivered", "in transit"]),
                    )
                )
                print(f"    5. + status filter: {cond5_result.scalar()}")


asyncio.run(test_query())
