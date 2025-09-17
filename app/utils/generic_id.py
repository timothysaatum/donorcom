from uuid import UUID
from app.models.blood_bank import BloodBank
from app.models.health_facility import Facility
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_
from fastapi import HTTPException, status
from sqlalchemy.future import select
from app.utils.logging_config import get_logger

logger = get_logger(__name__)




# Helper function to get facility ID for the current user
def get_user_facility_id(current_user: User) -> str:
    """
    Extract facility ID based on user role - handles edge cases.
    Priority: facility_administrator > lab_manager > staff
    """
    user_facility_id = None
    user_role_names = {
        role.name for role in current_user.roles
    }  # Use set for faster lookup

    logger.debug(
        "Extracting facility ID for user",
        extra={
            "event_type": "facility_id_extraction",
            "user_id": str(current_user.id),
            "user_roles": list(user_role_names),
            "user_email": current_user.email,
        },
    )

    # Check roles in priority order
    if "facility_administrator" in user_role_names:
        user_facility_id = current_user.facility.id if current_user.facility else None
        if not user_facility_id:
            logger.error(
                "Facility administrator without associated facility",
                extra={
                    "event_type": "facility_admin_missing_facility",
                    "user_id": str(current_user.id),
                    "user_email": current_user.email,
                },
            )
            raise HTTPException(
                status_code=400,
                detail="Facility administrator must be associated with a facility",
            )

    elif user_role_names & {"lab_manager", "staff"}:  # Intersection check
        user_facility_id = current_user.work_facility_id
        if not user_facility_id:
            logger.error(
                "Staff/lab manager without work facility",
                extra={
                    "event_type": "staff_missing_work_facility",
                    "user_id": str(current_user.id),
                    "user_email": current_user.email,
                    "user_roles": list(user_role_names),
                },
            )
            raise HTTPException(
                status_code=400,
                detail="Staff and lab managers must be associated with a work facility",
            )

    else:
        # User has roles but none that give facility access
        logger.warning(
            "User roles do not provide facility access",
            extra={
                "event_type": "insufficient_facility_access",
                "user_id": str(current_user.id),
                "user_email": current_user.email,
                "user_roles": list(user_role_names),
            },
        )
        raise HTTPException(
            status_code=403,
            detail=f"User roles {list(user_role_names)} do not provide facility access",
        )

    logger.debug(
        "Facility ID extracted successfully",
        extra={
            "event_type": "facility_id_extracted",
            "user_id": str(current_user.id),
            "facility_id": str(user_facility_id),
            "primary_role": next(
                iter(
                    user_role_names & {"facility_administrator", "lab_manager", "staff"}
                ),
                "unknown",
            ),
        },
    )

    return user_facility_id


# Helper function to get blood bank ID for the current user
async def get_user_blood_bank_id(db: AsyncSession, user_id: UUID) -> UUID:
    """Get the blood bank ID associated with the user"""

    result = await db.execute(
        select(BloodBank).where(
            or_(
                # Case 1: User is the blood bank manager
                BloodBank.manager_id == user_id,
                # Case 2: User is staff working in the facility
                BloodBank.facility_id
                == (
                    select(User.work_facility_id)
                    .where(User.id == user_id)
                    .scalar_subquery()
                ),
                # Case 3: User is the facility manager
                BloodBank.facility_id
                == (
                    select(Facility.id)
                    .where(Facility.facility_manager_id == user_id)
                    .scalar_subquery()
                ),
            )
        )
    )

    blood_bank = result.scalar_one_or_none()

    if blood_bank:
        return blood_bank.id

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You are not associated with any blood bank",
    )
