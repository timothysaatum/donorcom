import asyncio
from app.database import async_session
from sqlalchemy import select, func, and_
from app.models.distribution_model import BloodDistribution
from app.models.user_model import User
from app.models.blood_bank_model import BloodBank
from datetime import datetime, timedelta


async def test_for_admin1():
    async with async_session() as session:
        # Get admin1
        admin1_result = await session.execute(
            select(User).where(User.email == "admin1@example.com")
        )
        admin1 = admin1_result.scalar_one()

        print(f"Testing for admin1: {admin1.email}")
        print(f"User ID: {str(admin1.id)[:8]}...\n")

        # Get their blood bank
        bb_result = await session.execute(
            select(BloodBank).where(BloodBank.manager_id == admin1.id)
        )
        blood_bank = bb_result.scalar_one()

        print(f"Blood Bank: {blood_bank.blood_bank_name}")
        print(f"Blood Bank ID: {str(blood_bank.id)[:8]}...\n")

        # Test the distribution query
        to_date = datetime.now().replace(hour=23, minute=59, second=59)
        from_date = (to_date - timedelta(days=7)).replace(hour=0, minute=0, second=0)

        from_date_naive = (
            from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
        )
        to_date_naive = to_date.replace(tzinfo=None) if to_date.tzinfo else to_date

        conditions = [
            BloodDistribution.dispatched_from_id == blood_bank.id,
            BloodDistribution.date_delivered.is_not(None),
            BloodDistribution.date_delivered >= from_date_naive,
            BloodDistribution.date_delivered <= to_date_naive,
            BloodDistribution.status.in_(["delivered", "in transit"]),
        ]

        query = (
            select(
                func.date(BloodDistribution.date_delivered).label("distribution_date"),
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

        print(f"Distribution chart data for {blood_bank.blood_bank_name}:")
        print(f"Date range: {from_date_naive.date()} to {to_date_naive.date()}")
        print(f"Found {len(rows)} data points:\n")

        if rows:
            for row in rows:
                print(
                    f"  Date: {row[0]}, Product: {row[1]}, Type: {row[2]}, Quantity: {row[3]}"
                )
        else:
            print("  NO DATA FOUND!")

        # Now test for admin2
        print("\n" + "=" * 80 + "\n")

        admin2_result = await session.execute(
            select(User).where(User.email == "admin2@example.com")
        )
        admin2 = admin2_result.scalar_one()

        print(f"Testing for admin2: {admin2.email}")
        print(f"User ID: {str(admin2.id)[:8]}...\n")

        bb2_result = await session.execute(
            select(BloodBank).where(BloodBank.manager_id == admin2.id)
        )
        blood_bank2 = bb2_result.scalar_one()

        print(f"Blood Bank: {blood_bank2.blood_bank_name}")
        print(f"Blood Bank ID: {str(blood_bank2.id)[:8]}...\n")

        conditions2 = [
            BloodDistribution.dispatched_from_id == blood_bank2.id,
            BloodDistribution.date_delivered.is_not(None),
            BloodDistribution.date_delivered >= from_date_naive,
            BloodDistribution.date_delivered <= to_date_naive,
            BloodDistribution.status.in_(["delivered", "in transit"]),
        ]

        query2 = (
            select(
                func.date(BloodDistribution.date_delivered).label("distribution_date"),
                BloodDistribution.blood_product,
                BloodDistribution.blood_type,
                func.sum(BloodDistribution.quantity).label("daily_received"),
            )
            .where(and_(*conditions2))
            .group_by(
                func.date(BloodDistribution.date_delivered),
                BloodDistribution.blood_product,
                BloodDistribution.blood_type,
            )
        )

        result2 = await session.execute(query2)
        rows2 = result2.fetchall()

        print(f"Distribution chart data for {blood_bank2.blood_bank_name}:")
        print(f"Found {len(rows2)} data points:\n")

        if rows2:
            for row in rows2:
                print(
                    f"  Date: {row[0]}, Product: {row[1]}, Type: {row[2]}, Quantity: {row[3]}"
                )
        else:
            print("  NO DATA FOUND!")


asyncio.run(test_for_admin1())
