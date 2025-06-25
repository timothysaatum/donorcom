from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException
from app.models.user import User
from app.models.health_facility import Facility
from app.schemas.user import UserCreate, UserWithFacility, UserUpdate
from app.utils.security import get_password_hash, verify_password, create_access_token, create_verification_token
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import UUID
from fastapi import BackgroundTasks
from app.utils.email_verification import send_verification_email
from sqlalchemy.orm import selectinload



class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(
            self, user_data: UserCreate, 
            background_tasks: BackgroundTasks = None,
            facility_id: Optional[UUID] = None

            ) -> User:
        result = await self.db.execute(select(User).where(User.email == user_data.email))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")

        hashed_password = get_password_hash(user_data.password)
        verification_token = create_verification_token(user_data.email)

        created_user = User(
            email=user_data.email,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            password=hashed_password,
            role=user_data.role,
            phone=user_data.phone,
            verification_token=verification_token,
            facility_id=facility_id if facility_id else None,
            
        )

        self.db.add(created_user)
        await self.db.commit()
        await self.db.refresh(created_user)

        # Send verification email
        if background_tasks:
            background_tasks.add_task(send_verification_email, created_user.email, verification_token)

        return created_user

    async def authenticate_user(self, email: str, password: str) -> dict:

        result = await self.db.execute(
            select(User)
            .options(
                selectinload(User.facility).selectinload(Facility.blood_bank)
            )
            .where(User.email == email)
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(password, user.password):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if not user.is_verified:
            raise HTTPException(status_code=400, detail="User email not verified")

        # update last login
        user.last_login = datetime.now()
        await self.db.commit()

        token_data = {"sub": str(user.id), "email": user.email}
        access_token = create_access_token(data=token_data, expires_delta=timedelta(minutes=60))

        user_data = UserWithFacility.model_validate(user, from_attributes=True).model_dump()

        return {
            "access_token": access_token,
            "user": user_data
        }

    async def get_user(self, user_id: UUID) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
    
    async def update_user(self, user_id: UUID, user_data: UserUpdate) -> User:
        user = await self.get_user(user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not Found")

        if "role" in user_data.model_dump(exclude_unset=True):
            if user.role not in ["facility_administrator", "lab_manager"]:
                raise HTTPException(status_code=403, detail="You are not allowed to change your role")

        
        update_data = user_data.model_dump(exclude_unset=True)

        if "role" in update_data and user.role not in ["facility_administrator", "lab_manager"]:
            update_data.pop("role")
            
        for key, value in update_data.items():
            setattr(user, key, value)

        await self.db.commit()
        await self.db.refresh(user)
        return user
    
    async def delete_user(self, user_id: UUID) -> None:
        user = await self.get_user(user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        await self.db.delete(user)
        await self.db.commit()

    async def get_all_staff_users(self, facility_id: UUID) -> List[User]:
        """
        Get all staff and lab manager users for a given facility.
        """
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.facility))
            .where(
                User.facility_id == facility_id,
                User.role.in_(["staff", "lab_manager"])
            )
        )
        return result.scalars().all()