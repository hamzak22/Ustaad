from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class NotificationBase(BaseModel):
    notification_type: str
    title: str
    body: str
    entity_type: Optional[str] = None
    entity_id: Optional[UUID] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NotificationCreate(NotificationBase):
    recipient_id: UUID
    actor_id: Optional[UUID] = None


class NotificationItem(NotificationBase):
    notification_id: UUID
    recipient_id: UUID
    actor_id: Optional[UUID] = None
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    total_count: int
    unread_count: int


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int


class MarkReadResponse(BaseModel):
    message: str


class RealtimeEvent(BaseModel):
    event: str
    data: dict[str, Any]


class WebSocketHandshake(BaseModel):
    event: str = "connected"
    unread_count: int
    recent_notifications: list[NotificationItem]
