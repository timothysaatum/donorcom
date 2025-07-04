"""
Notification service for handling blood request notifications
"""

from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.request import BloodRequest
from app.models.user import User
from app.models.health_facility import Facility
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for handling notifications related to blood requests"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def notify_request_created(self, request_group_id: UUID, facility_ids: List[UUID]) -> None:
        """
        Notify facility managers about new blood requests
        
        Args:
            request_group_id: The group ID of the created requests
            facility_ids: List of facility IDs that received the request
        """
        try:
            # Get facility managers
            # result = await self.db.execute(
            #     select(User, Facility)
            #     .join(Facility, User.id == Facility.facility_manager_id)
            #     .where(Facility.id.in_(facility_ids))
            # )
            
            # facility_managers = result.fetchall()
            
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
            for manager, facility in facility_ids:
                await self._send_notification(
                    user_id=manager.id,
                    title="New Blood Request",
                    message=f"New request for {sample_request.blood_type} {sample_request.blood_product} "
                           f"(Qty: {sample_request.quantity_requested}) received at {facility.facility_name}",
                    notification_type="new_request",
                    related_request_id=sample_request.id
                )

            logger.info(f"Sent notifications for request group {request_group_id} to {len(facility_ids)} facility managers")
            
        except Exception as e:
            logger.error(f"Error sending request creation notifications: {str(e)}")
    
    async def notify_request_cancelled(self, cancelled_request_ids: List[UUID], reason: str) -> None:
        """
        Notify relevant parties about cancelled requests
        
        Args:
            cancelled_request_ids: List of request IDs that were cancelled
            reason: Reason for cancellation
        """
        try:
            # Get cancelled requests with facility and requester info
            result = await self.db.execute(
                select(BloodRequest, User, Facility)
                .join(User, BloodRequest.requester_id == User.id)
                .join(Facility, BloodRequest.facility_id == Facility.id)
                .where(BloodRequest.id.in_(cancelled_request_ids))
            )
            
            cancelled_requests = result.fetchall()
            
            # Notify requesters
            notified_requesters = set()
            for request, requester, facility in cancelled_requests:
                if requester.id not in notified_requesters:
                    await self._send_notification(
                        user_id=requester.id,
                        title="Request Cancelled",
                        message=f"Your blood request for {request.blood_type} {request.blood_product} "
                               f"has been cancelled. Reason: {reason}",
                        notification_type="request_cancelled",
                        related_request_id=request.id
                    )
                    notified_requesters.add(requester.id)
            
            # Notify facility managers
            facility_managers = {}
            for request, requester, facility in cancelled_requests:
                if facility.facility_manager_id not in facility_managers:
                    facility_managers[facility.facility_manager_id] = []
                facility_managers[facility.facility_manager_id].append((request, facility))
            
            for manager_id, requests_and_facilities in facility_managers.items():
                request_count = len(requests_and_facilities)
                sample_request, sample_facility = requests_and_facilities[0]
                
                await self._send_notification(
                    user_id=manager_id,
                    title="Requests Cancelled",
                    message=f"{request_count} blood request(s) at {sample_facility.facility_name} "
                           f"have been cancelled. Reason: {reason}",
                    notification_type="requests_cancelled",
                    related_request_id=sample_request.id
                )
            
            logger.info(f"Sent cancellation notifications for {len(cancelled_request_ids)} requests")
            
        except Exception as e:
            logger.error(f"Error sending cancellation notifications: {str(e)}")
    
    async def notify_request_status_change(self, request_id: UUID, old_status: str, new_status: str) -> None:
        """
        Notify relevant parties about request status changes
        
        Args:
            request_id: ID of the request that changed status
            old_status: Previous status
            new_status: New status
        """
        try:
            # Get request details
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
            
            # Notify requester
            status_messages = {
                'approved': f"Your blood request for {request.blood_type} {request.blood_product} "
                           f"has been approved by {facility.facility_name}",
                'rejected': f"Your blood request for {request.blood_type} {request.blood_product} "
                           f"has been rejected by {facility.facility_name}",
                'fulfilled': f"Your blood request for {request.blood_type} {request.blood_product} "
                            f"has been fulfilled by {facility.facility_name}"
            }
            
            if new_status in status_messages:
                await self._send_notification(
                    user_id=requester.id,
                    title=f"Request {new_status.title()}",
                    message=status_messages[new_status],
                    notification_type=f"request_{new_status}",
                    related_request_id=request.id
                )
            
            logger.info(f"Sent status change notification for request {request_id}: {old_status} -> {new_status}")
            
        except Exception as e:
            logger.error(f"Error sending status change notification: {str(e)}")
    
    async def _send_notification(
        self, 
        user_id: UUID, 
        title: str, 
        message: str, 
        notification_type: str,
        related_request_id: Optional[UUID] = None
    ) -> None:
        """
        Send a notification to a user
        
        This is a placeholder method. In a real implementation, you might:
        - Store notifications in a database table
        - Send push notifications
        - Send emails
        - Send SMS messages
        - Use a message queue system
        """
        
        # Example: Store in database (you'd need to create a Notification model)
        # notification = Notification(
        #     user_id=user_id,
        #     title=title,
        #     message=message,
        #     notification_type=notification_type,
        #     related_request_id=related_request_id,
        #     created_at=datetime.utcnow(),
        #     is_read=False
        # )
        # self.db.add(notification)
        # await self.db.commit()
        
        # For now, just log the notification
        logger.info(f"NOTIFICATION - User {user_id}: {title} - {message}")
    
    async def get_user_notifications(self, user_id: UUID, limit: int = 50) -> List[dict]:
        """
        Get notifications for a user
        
        This is a placeholder method. In a real implementation, you'd query
        the notifications table and return the results.
        """
        # Placeholder implementation
        return []
    
    async def mark_notification_as_read(self, notification_id: UUID, user_id: UUID) -> bool:
        """
        Mark a notification as read
        
        Args:
            notification_id: ID of the notification to mark as read
            user_id: ID of the user (for security)
            
        Returns:
            True if successful, False otherwise
        """
        # Placeholder implementation
        return True