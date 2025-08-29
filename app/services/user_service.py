from asyncio.log import logger
from unittest import result
from app.models.rbac import Role
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException
from app.models.user import User
from app.models.health_facility import Facility
from app.schemas.user import UserCreate, UserWithFacility, UserUpdate
from app.utils.security import get_password_hash, verify_password, TokenManager, create_verification_token
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import UUID
from sqlalchemy import and_
from fastapi import BackgroundTasks
from app.utils.email_verification import send_verification_email
from sqlalchemy.orm import selectinload



class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(
            self, user_data: UserCreate, 
            background_tasks: BackgroundTasks = None,
            facility_id: Optional[UUID] = None,
            work_facility_id: Optional[UUID] = None
            ) -> User:
        
        email = user_data.email.strip().lower()
        result = await self.db.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")

        hashed_password = get_password_hash(user_data.password)
        # verification_token = create_verification_token(user_data.email)
        facility_id = facility_id or work_facility_id

        verification_token = create_verification_token(
            email=user_data.email,
            role=user_data.role,
            facility_id=str(facility_id) if facility_id else None
        )

        created_user = User(
            email=user_data.email,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            password=hashed_password,
            phone=user_data.phone,
            verification_token=verification_token,
            work_facility_id=work_facility_id if work_facility_id else None
        )

        self.db.add(created_user)
        await self.db.commit()
        await self.db.refresh(created_user)

        # Send verification email
        if background_tasks:
            background_tasks.add_task(
                send_verification_email, 
                created_user.email, 
                verification_token
            )

        return created_user

    async def get_user(self, user_id: UUID) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
    
    async def update_user(self, user_id: UUID, user_data: UserUpdate) -> User:
        user = await self.get_user(user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not Found")
        
        update_data = user_data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(user, key, value)

        await self.db.commit()
        await self.db.refresh(user)
        return user
    
    async def delete_user(self, user_id: UUID) -> None:
        
        # fetch the user with relationships loaded
        result = await self.db.execute(
            select(User)
            .options(
                selectinload(User.facility),
                selectinload(User.blood_bank)
            )
                .where(User.id == user_id)
            )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Delete associated facility if exists
        if user.facility:
            await self.db.delete(user.facility)

        # Delete associated blood bank if exists
        if user.blood_bank:
            await self.db.delete(user.blood_bank)

        await self.db.delete(user)
        await self.db.commit()

    async def get_all_staff_users(self, facility_id: UUID) -> List[User]:
        """
        Get all staff and lab manager users for a given facility.
        """
        result = await self.db.execute(
        select(User)
        .join(User.roles)
        .options(
            selectinload(User.work_facility),
            selectinload(User.roles)  # Load user roles
        )
        .where(
            User.work_facility_id == facility_id,
            Role.name.in_(["staff", "lab_manager"])
        )
        .distinct()  # Prevents duplicates if user has multiple matching roles
    )
        return result.scalars().all()
