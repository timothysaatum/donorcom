import datetime
from typing import List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.request_model import BloodRequest
from app.models.user_model import User
from app.models.health_facility_model import Facility
from app.services.notification_sse import manager
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for handling notifications with WebSocket integration"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def notify_request_created(
        self, request_group_id: UUID, facility_managers: List[tuple]
    ) -> None:
        """Notify facility managers about new blood requests"""
        try:
            # Get request details
            request_result = await self.db.execute(
                select(BloodRequest)
                .where(BloodRequest.request_group_id == request_group_id)
                .limit(1)
            )
            sample_request = request_result.scalar_one_or_none()

            if not sample_request:
                return

            # Send notifications to each facility manager
            for manager_user, facility in facility_managers:
                notification = {
                    "type": "new_request",
                    "title": "New Blood Request",
                    "message": f"New request for {sample_request.blood_type} {sample_request.blood_product} "
                    f"(Qty: {sample_request.quantity_requested}) received at {facility.facility_name}",
                    "request_id": str(sample_request.id),
                    "request_group_id": str(request_group_id),
                    "facility_name": facility.facility_name,
                    "timestamp": datetime.now(datetime.timezone.utc).isoformat(),
                    "priority": (
                        "high" if sample_request.priority == "not_urgent" else "normal"
                    ),
                }

                # Send via WebSocket if user is connected
                await self._send_notification(manager_user.id, notification)

            logger.info(
                f"Sent notifications for request group {request_group_id} to {len(facility_managers)} facility managers"
            )

        except Exception as e:
            logger.error(f"Error sending request creation notifications: {str(e)}")

    async def notify_request_status_change(
        self, request_id: UUID, old_status: str, new_status: str
    ) -> None:
        """Notify relevant parties about request status changes"""
        try:
            # Get request details with relationships
            result = await self.db.execute(
                select(BloodRequest, User, Facility)
                .join(User, BloodRequest.requester_id == User.id)
                .join(Facility, BloodRequest.facility_id == Facility.id)
                .where(BloodRequest.id == request_id)
            )

            request_data = result.fetchone()
            if not request_data:
                return

            request, requester, facility = request_data

            # Create notification
            status_messages = {
                "approved": f"Your blood request for {request.blood_type} {request.blood_product} has been approved by {facility.facility_name}",
                "rejected": f"Your blood request for {request.blood_type} {request.blood_product} has been rejected by {facility.facility_name}",
                "fulfilled": f"Your blood request for {request.blood_type} {request.blood_product} has been fulfilled by {facility.facility_name}",
            }

            if new_status in status_messages:
                notification = {
                    "type": f"request_{new_status}",
                    "title": f"Request {new_status.title()}",
                    "message": status_messages[new_status],
                    "request_id": str(request_id),
                    "old_status": old_status,
                    "new_status": new_status,
                    "facility_name": facility.facility_name,
                    "timestamp": datetime.now(datetime.timezone.utc).isoformat(),
                    "priority": (
                        "high" if new_status in ["approved", "fulfilled"] else "normal"
                    ),
                }

                # Send to requester
                await self._send_notification(requester.id, notification)

            logger.info(
                f"Sent status change notification for request {request_id}: {old_status} -> {new_status}"
            )

        except Exception as e:
            logger.error(f"Error sending status change notification: {str(e)}")

    async def _send_notification(self, user_id: UUID, notification: dict) -> None:
        """Send notification via SSE and store in database"""
        try:
            # Send via SSE if user is connected
            success = await manager.send_personal_message(str(user_id), notification)

            if success:
                logger.info(
                    f"SSE notification sent to user {user_id}: {notification['title']}"
                )
            else:
                logger.info(
                    f"User {user_id} not connected, notification queued: {notification['title']}"
                )

            # TODO: Store in database for offline users
            # await self._store_notification_in_db(user_id, notification)

        except Exception as e:
            logger.error(f"Error sending notification to user {user_id}: {e}")

    async def broadcast_system_message(
        self, message: str, message_type: str = "system"
    ) -> int:
        """Broadcast a system message to all connected users"""
        notification = {
            "type": message_type,
            "title": "System Message",
            "message": message,
            "timestamp": datetime.now(datetime.timezone.utc).isoformat(),
            "priority": "normal",
        }

        sent_count = await manager.broadcast(notification)
        logger.info(f"System message broadcast to {sent_count} connections")
        return sent_count
