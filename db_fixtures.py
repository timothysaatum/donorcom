import asyncio
from datetime import date, timedelta
from random import choice, randint
from app.models.blood_bank import BloodBank
from app.models.health_facility import Facility
from app.models.inventory import BloodInventory
from app.models.user import User
from app.utils.security import get_password_hash
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.utils import supervisor


DATABASE_URL = "sqlite+aiosqlite:///./db.sqlite3"
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


blood_types = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
valid_products = [
    'Whole Blood','whole blood','Red Blood Cells','red blood cells',
    'Plasma','Platelets','platelets','Cryoprecipitate','cryoprecipitate',
    'Fresh Frozen Plasma','fresh frozen plasma','Albumin','albumin',
    'red cells','Red Cells'
]

async def seed_db():
    async with AsyncSessionLocal() as db:
        async with db.begin():
            # --- 1. Create 2 admin users ---
            admin_users = []
            credentials_list = []
            for i in range(2):
                email = f"admin{i+1}@example.com"
                password = "SecureP@ssw0rd!"
                hashed_password = get_password_hash(password)
                user = User(
                    first_name=f"Admin{i+1}",
                    last_name="User",
                    email=email,
                    phone=f"+2335000000{i+1}",
                    password=hashed_password,
                    is_verified=True,
                )
                db.add(user)

                await db.flush()  # assign ID
                
                await supervisor.assign_role(
                    db, user_id=user.id, 
                    role_name="facility_administrator", 
                    auto_commit=False
                )
                
                admin_users.append(user)
                # Save credentials for devs
                credentials_list.append(f"{email} | {password}")

            # Save credentials to file
            with open("dev_credentials.txt", "w") as f:
                f.write("\n".join(credentials_list))

            # --- 2. Create 2 facilities and attach to users ---
            facilities = []
            for i, user in enumerate(admin_users):
                facility = Facility(
                    facility_name=f"Tamale Teaching Hospital {i+1}",
                    facility_email=f"email{i+1}@tth.org",
                    facility_contact_number=f"+2337000000{i+1}",
                    facility_digital_address=f"DA-1902{i+1}-2345",
                    facility_manager_id=user.id
                )
                db.add(facility)
                await db.flush()
                facilities.append(facility)

                # --- 3. Create BloodBank and attach to Facility ---
                blood_bank = BloodBank(
                    blood_bank_name=f"BloodBank{i+1}",
                    phone=f"+2336000000{i+1}",
                    email=f"bloodbank{i+1}@example.com",
                    facility_id=facility.id,
                    manager_id=user.id
                )
                db.add(blood_bank)
                await db.flush()

                # Link facility to blood bank
                facility.blood_bank = blood_bank

                # --- 4. Add 10 BloodInventory items to this blood bank ---
                for _ in range(10):
                    inventory = BloodInventory(
                        blood_product=choice(valid_products),
                        blood_type=choice(blood_types),
                        quantity=randint(1, 10),
                        expiry_date=date.today() + timedelta(days=randint(30, 180)),
                        blood_bank_id=blood_bank.id,
                        added_by_id=user.id
                    )
                    db.add(inventory)

        await db.commit()
        print("Created 2 test users, 2 facilities, and 20 blood inventory items!")
        print("Dev credentials saved to dev_credentials.txt")

if __name__ == "__main__":
    asyncio.run(seed_db())
