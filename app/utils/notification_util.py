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
    Notify ALL active users in specified facilities instantly via SSE.

    This ensures that EVERYONE in the facility sees the notification, regardless of:
    - Their current shift status
    - Whether they created the request
    - Their role or permissions

    Perfect for shift handovers where staff need to see pending requests
    created by colleagues who have ended their shift.

    Args:
        db: Database session
        facility_ids: List of facility IDs whose users should be notified
        title: Notification title
        message: Notification message
        extra_data: Optional additional data to include in SSE payload (e.g., request_id, type)
    """
    try:
        # Query ALL active users in the target facilities
        # Note: Only checking is_active=True (not status) to include all active accounts
        result = await db.execute(
            select(User.id, User.email, User.first_name, User.last_name).where(
                User.work_facility_id.in_(facility_ids),
                User.is_active == True,  # Only active accounts
                # Removed status check - notify everyone regardless of online/offline status
            )
        )
        facility_users = result.all()

        if not facility_users:
            logger.warning(
                f"No active users found in facilities: {[str(fid)[:8] + '...' for fid in facility_ids]}"
            )
            return

        # Create notification records in DB for all users
        # These persist even if users are offline and can be viewed later
        notifications = []
        for user in facility_users:
            notification = Notification(user_id=user.id, title=title, message=message)
            notifications.append(notification)

        db.add_all(notifications)
        await db.commit()

        # Prepare SSE payload with all data
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "title": title,
            "message": message,
            "timestamp": timestamp,
            "facility_wide": True,  # Flag to indicate this is a facility-wide notification
        }

        # Add extra data if provided (e.g., request_id, distribution_id, type)
        if extra_data:
            payload.update(extra_data)

        # Get SSE manager ONCE (reuse connection manager)
        manager = ConnectionManager()

        # Send to all facility users INSTANTLY using concurrent delivery
        # This ensures INSTANT notification delivery to all connected users
        user_ids = [str(user.id) for user in facility_users]

        # Send all notifications concurrently for INSTANT delivery
        send_tasks = [
            manager.send_personal_message(user_id, payload) for user_id in user_ids
        ]

        # Wait for all to be sent (ensures instant delivery, not fire-and-forget)
        results = await asyncio.gather(*send_tasks, return_exceptions=True)

        # Count successful deliveries
        success_count = sum(1 for r in results if r is True)

        logger.info(
            f"Facility-wide notification sent INSTANTLY to {success_count}/{len(facility_users)} users "
            f"in {len(facility_ids)} facility(ies): '{title}' - {message[:50]}..."
        )

    except Exception as e:
        await db.rollback()
        logger.error(
            f"Failed to send facility notifications to {facility_ids}: {str(e)}",
            exc_info=True,
        )
