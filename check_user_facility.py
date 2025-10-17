import asyncio
from app.database import async_session
from sqlalchemy import select
from app.models.user_model import User
from app.models.health_facility_model import Facility
from app.models.blood_bank_model import BloodBank


async def check_user_facility():
    async with async_session() as session:
        # Get all users
        users_result = await session.execute(
            select(User.id, User.email, User.work_facility_id)
        )
        users = users_result.all()

        print("=== Users and their facilities ===")
        for user in users:
            print(f"User: {user[1]} (ID: {str(user[0])[:8]}...)")
            print(
                f"  work_facility_id: {str(user[2])[:8] + '...' if user[2] else 'None'}"
            )

        # Get all facilities
        print("\n=== All Facilities ===")
        facilities_result = await session.execute(
            select(Facility.id, Facility.facility_name)
        )
        facilities = facilities_result.all()
        for fac in facilities:
            print(f"Facility: {fac[1]} (ID: {str(fac[0])[:8]}...)")

        # Get all blood banks with their facility_id
        print("\n=== All Blood Banks ===")
        blood_banks_result = await session.execute(
            select(BloodBank.id, BloodBank.blood_bank_name, BloodBank.facility_id)
        )
        blood_banks = blood_banks_result.all()
        for bb in blood_banks:
            print(f"Blood Bank: {bb[1]} (ID: {str(bb[0])[:8]}...)")
            print(f"  facility_id: {str(bb[2])[:8] + '...' if bb[2] else 'None'}")


asyncio.run(check_user_facility())
