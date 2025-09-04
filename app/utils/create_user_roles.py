from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.models.rbac import Role, Permission
import logging

# Set up logging
logger = logging.getLogger(__name__)

DEFAULT_ROLES = {
    "moderator": [
        "impersonate.start",
        "impersonate.end",
        "impersonate.view_audit",
        "impersonate.facility",
    ],
    "facility_administrator": ["facility.manage", "account.can_view_profile"],
    "lab_manager": [
        "laboratory.can_update",
        "laboratory.can_view",
        "inventory.manage",
        "request.manage",
        "distribution.manage",
        "staff.manage",
        "account.can_view_profile",
    ],
    "staff": [
        "blood.inventory.manage",
        "blood.request.can_create",
        "blood.request.can_view",
        "blood.request.can_approve",
        "blood.request.can_update",
        "blood.issue.can_create",
        "blood.issue.can_approve",
        "blood.issue.can_update",
        "blood.issue.can_view",
        "blood.issue.can_delete",
        "account.can_view_profile",
    ],
}


async def seed_roles_and_permissions(db: AsyncSession):
    """
    Seed roles and permissions with robust error handling.
    This function will not crash the application if seeding fails.
    """
    try:
        logger.info("Starting role and permission seeding...")

        for role_name, perms in DEFAULT_ROLES.items():
            try:
                logger.debug(f"Processing role: {role_name}")

                # Get or create role with individual error handling
                role = await get_or_create_role(db, role_name)

                # Process permissions for this role
                await process_role_permissions(db, role, perms, role_name)

            except Exception as role_error:
                logger.error(f"Error processing role '{role_name}': {role_error}")
                # Continue with other roles even if one fails
                continue

        await db.commit()
        logger.info("Successfully completed role and permission seeding!")

    except Exception as e:
        logger.error(f"Critical error during seeding: {e}")
        try:
            await db.rollback()
            logger.info("Successfully rolled back database transaction")
        except Exception as rollback_error:
            logger.error(f"Error during rollback: {rollback_error}")

        # Log the error but don't raise it to prevent application startup failure
        logger.warning("Seeding failed, but application will continue to start")


async def get_or_create_role(db: AsyncSession, role_name: str) -> Role:
    """Get existing role or create new one."""
    try:
        result = await db.execute(select(Role).where(Role.name == role_name))
        role = result.scalar_one_or_none()

        if not role:
            role = Role(name=role_name)
            db.add(role)
            await db.flush()
            logger.info(f"Created new role: {role_name}")
        else:
            logger.debug(f"Role already exists: {role_name}")

        return role

    except IntegrityError as e:
        # Handle race condition where role was created between check and insert
        await db.rollback()
        result = await db.execute(select(Role).where(Role.name == role_name))
        role = result.scalar_one()
        logger.debug(f"Role '{role_name}' already exists (race condition handled)")
        return role


async def process_role_permissions(
    db: AsyncSession, role: Role, perms: list, role_name: str
):
    """Process permissions for a given role."""
    # Load existing permissions for this role to avoid duplicates
    await db.refresh(role)
    result = await db.execute(
        select(Role).options(selectinload(Role.permissions)).where(Role.id == role.id)
    )
    role_with_perms = result.scalar_one()
    existing_perm_names = {perm.name for perm in role_with_perms.permissions}

    for perm_name in perms:
        try:
            # Get or create permission
            permission = await get_or_create_permission(db, perm_name)

            # Add permission to role if not already present
            if perm_name not in existing_perm_names:
                role_with_perms.permissions.append(permission)
                logger.debug(f"Added permission '{perm_name}' to role '{role_name}'")
            else:
                logger.debug(
                    f"Permission '{perm_name}' already assigned to role '{role_name}'"
                )

        except Exception as perm_error:
            logger.error(
                f"Error processing permission '{perm_name}' for role '{role_name}': {perm_error}"
            )
            # Continue with other permissions even if one fails
            continue


async def get_or_create_permission(db: AsyncSession, perm_name: str) -> Permission:
    """Get existing permission or create new one."""
    try:
        result = await db.execute(
            select(Permission).where(Permission.name == perm_name)
        )
        perm = result.scalar_one_or_none()

        if not perm:
            perm = Permission(name=perm_name)
            db.add(perm)
            await db.flush()
            logger.debug(f"Created new permission: {perm_name}")

        return perm

    except IntegrityError as e:
        # Handle race condition where permission was created between check and insert
        await db.rollback()
        result = await db.execute(
            select(Permission).where(Permission.name == perm_name)
        )
        perm = result.scalar_one()
        logger.debug(
            f"Permission '{perm_name}' already exists (race condition handled)"
        )
        return perm