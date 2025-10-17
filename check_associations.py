import asyncio
from app.database import async_session
from sqlalchemy import select
from app.models.user_model import User
from app.models.health_facility_model import Facility
from app.models.blood_bank_model import BloodBank


async def check_associations():
    async with async_session() as session:
        # Get users
        users_result = await session.execute(select(User.id, User.email))
        users = users_result.all()

        for user in users:
            user_id, user_email = user
            print(f"\n=== User: {user_email} ({str(user_id)[:8]}...) ===")

            # Check if blood bank manager
            bb_result = await session.execute(
                select(BloodBank.id, BloodBank.blood_bank_name).where(
                    BloodBank.manager_id == user_id
                )
            )
            blood_banks = bb_result.all()
            if blood_banks:
                print(f"  Is manager of blood banks:")
                for bb in blood_banks:
                    print(f"    - {bb[1]} ({str(bb[0])[:8]}...)")
            else:
                print(f"  NOT a blood bank manager")

            # Check if facility manager
            fac_result = await session.execute(
                select(Facility.id, Facility.facility_name).where(
                    Facility.facility_manager_id == user_id
                )
            )
            facilities = fac_result.all()
            if facilities:
                print(f"  Is manager of facilities:")
                for fac in facilities:
                    print(f"    - {fac[1]} ({str(fac[0])[:8]}...)")
            else:
                print(f"  NOT a facility manager")


asyncio.run(check_associations())
