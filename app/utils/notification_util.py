import asyncio
import logging
from datetime import datetime, timezone
from typing import List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.notification_model import Notification
from app.models.user_model import User
from app.services.notification_sse import ConnectionManager

logger = logging.getLogger(__name__)


async def notify(db, user_id: UUID, title: str, message: str) -> None:
    """
    Create a notification in DB and push it over SSE.
    Fire-and-forget for real-time delivery without blocking.
    """
    try:
        # DB record
        new_notification = Notification(user_id=user_id, title=title, message=message)
        db.add(new_notification)

        payload = {
            "title": title,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Commit to DB
        await db.commit()
        manager = ConnectionManager()
        # Non-blocking SSE push
        asyncio.create_task(manager.send_personal_message(str(user_id), payload))

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to send notification to {user_id}: {str(e)}")


async def notify_facility(
    db: AsyncSession,
    facility_ids: List[UUID],
    title: str,
    message: str,
    extra_data: dict = None,
) -> None:
    """
    Notify all active users in specified facilities instantly via SSE.
    Creates DB records and pushes to all connected SSE clients without blocking.

    Args:
        db: Database session
        facility_ids: List of facility IDs whose users should be notified
        title: Notification title
        message: Notification message
        extra_data: Optional additional data to include in SSE payload
    """
    try:
        # Query all active users in the target facilities
        result = await db.execute(
            select(User.id, User.email, User.first_name, User.last_name).where(
                User.work_facility_id.in_(facility_ids),
                User.is_active == True,
                User.status == True,
            )
        )
        facility_users = result.all()

        if not facility_users:
            logger.warning(f"No active users found in facilities: {facility_ids}")
            return

        # Create notification records in DB for all users
        notifications = []
        for user in facility_users:
            notification = Notification(user_id=user.id, title=title, message=message)
            notifications.append(notification)

        db.add_all(notifications)
        await db.commit()

        # Prepare SSE payload
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {"title": title, "message": message, "timestamp": timestamp}

        # Add extra data if provided
        if extra_data:
            payload.update(extra_data)

        # Get SSE manager
        manager = ConnectionManager()

        # Send to all facility users instantly without blocking
        # Use create_task to make it truly non-blocking
        user_ids = [str(user.id) for user in facility_users]
        for user_id in user_ids:
            asyncio.create_task(manager.send_personal_message(user_id, payload))

        logger.info(
            f"Facility-wide notification sent to {len(facility_users)} users "
            f"in {len(facility_ids)} facilities: {title}"
        )

    except Exception as e:
        await db.rollback()
        logger.error(
            f"Failed to send facility notifications to {facility_ids}: {str(e)}",
            exc_info=True,
        )
