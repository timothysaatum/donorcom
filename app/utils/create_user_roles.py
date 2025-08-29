from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.rbac import Role, Permission

DEFAULT_ROLES = {
    "moderator": [
        "impersonate.start", 
        "impersonate.end", 
        "impersonate.view_audit",
        "impersonate.facility"
    ],
    "facility_administrator": [
        "facility.manage",
        "account.can_view_profile"
    ],
    "lab_manager": [
        "laboratory.can_update",
        "laboratory.can_view",
        "inventory.manage", 
        "request.manage", 
        "distribution.manage",
        "staff.manage"
        "account.can_view_profile"
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
        "account.can_view_profile"
    ]
}

async def seed_roles_and_permissions(db: AsyncSession):
    try:
        for role_name, perms in DEFAULT_ROLES.items():
            print(f"Processing role: {role_name}")
            
            # Get or create role
            result = await db.execute(select(Role).where(Role.name == role_name))
            role = result.scalar_one_or_none()
            
            if not role:
                role = Role(name=role_name)
                db.add(role)
                await db.flush()  # Flush to get the ID
                print(f"Created new role: {role_name}")
            else:
                print(f"Role already exists: {role_name}")

            # Load existing permissions for this role to avoid duplicates
            await db.refresh(role)
            result = await db.execute(
                select(Role).options(selectinload(Role.permissions))
                .where(Role.id == role.id)
            )
            role_with_perms = result.scalar_one()
            existing_perm_names = {perm.name for perm in role_with_perms.permissions}

            for perm_name in perms:
                # Get or create permission
                result = await db.execute(select(Permission).where(Permission.name == perm_name))
                perm = result.scalar_one_or_none()
                
                if not perm:
                    perm = Permission(name=perm_name)
                    db.add(perm)
                    await db.flush()  # Flush to get the ID
                    print(f"Created new permission: {perm_name}")
                
                # Add permission to role if not already present
                if perm_name not in existing_perm_names:
                    role_with_perms.permissions.append(perm)
                    print(f"Added permission '{perm_name}' to role '{role_name}'")
        
        await db.commit()
        print("Successfully seeded all roles and permissions!")
        
    except Exception as e:
        await db.rollback()
        print(f"Error during seeding: {e}")
        raise