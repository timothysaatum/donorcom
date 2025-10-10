"""
Notification Schemas for API Request/Response validation
"""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class NotificationBase(BaseModel):
    """Base schema for notification"""

    title: str = Field(..., max_length=255, description="Notification title")
    message: str = Field(..., max_length=500, description="Notification message")


class NotificationCreate(NotificationBase):
    """Schema for creating a notification"""

    user_id: UUID = Field(..., description="ID of the user to send notification to")


class NotificationUpdate(BaseModel):
    """Schema for updating a notification"""

    is_read: bool = Field(..., description="Mark notification as read/unread")


class NotificationResponse(NotificationBase):
    """Schema for notification response"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Notification ID")
    user_id: UUID = Field(..., description="User ID")
    is_read: bool = Field(..., description="Read status")
    created_at: datetime = Field(..., description="Creation timestamp")


class NotificationBatchUpdate(BaseModel):
    """Schema for batch updating notifications"""

    notification_ids: list[UUID] = Field(
        ..., description="List of notification IDs to update", min_length=1
    )
    is_read: bool = Field(..., description="Mark as read/unread")


class NotificationStats(BaseModel):
    """Schema for notification statistics"""

    total_notifications: int = Field(..., description="Total number of notifications")
    unread_count: int = Field(..., description="Number of unread notifications")
    read_count: int = Field(..., description="Number of read notifications")
