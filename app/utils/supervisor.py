from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.user import User
from app.models.rbac import Role
from uuid import UUID


async def assign_role(
        db: AsyncSession, 
        user_id: UUID, 
        role_name: str, 
        auto_commit: bool = True
    ):
    # Load user and eagerly fetch roles to avoid async lazy-loading issues
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    result = await db.execute(select(Role).where(Role.name == role_name))
    role = result.scalar_one_or_none()
    if not role:
        raise ValueError("Role not found")


    if role not in user.roles:
        user.roles.append(role)
        if auto_commit:  # only commit if not in outer transaction
            await db.commit()


    return user
