import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import and_, func, desc, or_
from fastapi import HTTPException, BackgroundTasks
from app.models.user import User
from app.models.rbac import Role
from app.schemas.user import UserCreate, UserUpdate
from app.utils.security import (
    get_password_hash,
    create_verification_token,
)
from app.utils.email_verification import send_verification_email
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID

# Performance optimized logger
logger = logging.getLogger(__name__)


class UserService:
    """Optimized user service for hospital staff management"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(
        self,
        user_data: UserCreate,
        background_tasks: BackgroundTasks = None,
        facility_id: Optional[UUID] = None,
        work_facility_id: Optional[UUID] = None,
    ) -> User:
        """Create new hospital staff user with optimized database operations"""

        email = user_data.email.strip().lower()

        # Optimized existence check with index usage
        result = await self.db.execute(
            select(User.id).where(User.email == email).limit(1)
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")

        # Password security
        hashed_password = get_password_hash(user_data.password)
        facility_id = facility_id or work_facility_id

        verification_token = create_verification_token(
            email=user_data.email,
            role=user_data.role.value,
            facility_id=str(facility_id) if facility_id else None,
        )

        # Create user with minimal data
        created_user = User(
            email=email,
            first_name=user_data.first_name.strip(),
            last_name=user_data.last_name.strip(),
            password=hashed_password,
            phone=user_data.phone.strip() if user_data.phone else None,
            verification_token=verification_token,
            work_facility_id=work_facility_id,
            is_verified=False,  # Require email verification
            is_active=True,
        )

        self.db.add(created_user)
        await self.db.commit()
        await self.db.refresh(created_user)

        # Background email verification
        if background_tasks:
            background_tasks.add_task(
                send_verification_email, created_user.email, verification_token
            )

        return created_user

    async def get_user(self, user_id: UUID) -> Optional[User]:
        """Get user with optimized relationship loading"""
        result = await self.db.execute(
            select(User)
            .options(
                selectinload(User.roles),
                selectinload(User.work_facility),
                selectinload(User.facility),
            )
            .where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_users_paginated(
        self,
        skip: int = 0,
        limit: int = 50,
        facility_id: Optional[UUID] = None,
        role_name: Optional[str] = None,
        search: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Get paginated users with optimized filtering for hospital staff"""

        # Build base query with performance optimizations
        query = select(User).options(
            selectinload(User.roles), selectinload(User.work_facility)
        )

        # Apply filters using indexed columns
        conditions = []

        if facility_id:
            conditions.append(User.work_facility_id == facility_id)

        if is_active is not None:
            conditions.append(User.is_active == is_active)

        if search:
            search_term = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(User.first_name).contains(search_term),
                    func.lower(User.last_name).contains(search_term),
                    func.lower(User.email).contains(search_term),
                    func.lower(User.role).contains(search_term)
                )
            )

        if conditions:
            query = query.where(and_(*conditions))

        # Get total count efficiently
        count_query = select(func.count(User.id))
        if conditions:
            count_query = count_query.where(and_(*conditions))

        total_result = await self.db.execute(count_query)
        total_count = total_result.scalar()

        # Get paginated results
        query = query.order_by(desc(User.created_at)).offset(skip).limit(limit)
        result = await self.db.execute(query)
        users = result.scalars().all()

        return {
            "users": users,
            "total": total_count,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + limit) < total_count,
        }

    async def update_user(self, user_id: UUID, user_data: UserUpdate) -> User:
        """Update user with optimized database operations"""

        # Fetch user efficiently
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Apply updates with validation
        update_data = user_data.model_dump(exclude_unset=True)

        # Email uniqueness check if email is being updated
        if "email" in update_data and update_data["email"] != user.email:
            email_check = await self.db.execute(
                select(User.id)
                .where(and_(User.email == update_data["email"], User.id != user_id))
                .limit(1)
            )
            if email_check.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Email already in use")

        # Apply updates
        for key, value in update_data.items():
            if hasattr(user, key):
                if key == "email":
                    value = value.strip().lower()
                elif key in ["first_name", "last_name"] and value:
                    value = value.strip()
                setattr(user, key, value)

        user.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def delete_user(self, user_id: UUID) -> bool:
        """Soft delete user with relationship cleanup"""

        # Fetch user with minimal data needed
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Soft delete by deactivating
        user.is_active = False
        user.status = False
        user.is_banned = True
        user.is_locked = True
        user.is_suspended = True
        user.updated_at = datetime.now(timezone.utc)

        # Revoke all active sessions and tokens
        user.revoke_all_refresh_tokens()
        user.terminate_all_sessions()

        await self.db.commit()
        return True

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email with optimized query"""
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.roles), selectinload(User.work_facility))
            .where(User.email == email.strip().lower())
        )
        return result.scalar_one_or_none()

    async def verify_user_email(self, token: str) -> bool:
        """Verify user email with token"""
        result = await self.db.execute(
            select(User).where(User.verification_token == token)
        )
        user = result.scalar_one_or_none()

        if not user:
            return False

        user.is_verified = True
        user.verification_token = None
        user.updated_at = datetime.utcnow()

        await self.db.commit()
        return True

    async def get_facility_staff_count(self, facility_id: UUID) -> int:
        """Get active staff count for a facility"""
        result = await self.db.execute(
            select(func.count(User.id)).where(
                and_(
                    User.work_facility_id == facility_id,
                    User.is_active == True,
                    User.status == True,
                )
            )
        )
        return result.scalar() or 0

    async def get_all_staff_users(self, facility_id: UUID) -> List[User]:
        """Get all staff and lab manager users for a given facility with optimized query"""
        result = await self.db.execute(
            select(User)
            .join(User.roles)
            .options(selectinload(User.work_facility), selectinload(User.roles))
            .where(
                and_(
                    User.work_facility_id == facility_id,
                    User.is_active == True,
                    Role.name.in_(["staff", "lab_manager"]),
                )
            )
            .distinct()  # Prevents duplicates if user has multiple matching roles
        )
        return result.scalars().all()
