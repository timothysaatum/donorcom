import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID
from app.models.notification import Notification
from app.services.notification_ws import ConnectionManager  
logger = logging.getLogger(__name__)


async def notify(db, user_id: UUID, title: str, message: str) -> None:
    """
    Create a notification in DB and push it over WebSocket.
    Fire-and-forget for real-time delivery without blocking.
    """
    try:
        # DB record
        new_notification = Notification(
            user_id=user_id,
            title=title,
            message=message
        )
        db.add(new_notification)

        payload = {
            "title": title,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Commit to DB
        await db.commit()
        manager = ConnectionManager()
        # Non-blocking WebSocket push
        asyncio.create_task(manager.send_personal_message(str(user_id), payload))

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to send notification to {user_id}: {str(e)}")
