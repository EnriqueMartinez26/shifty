from datetime import datetime

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    public_id: str
    type: str
    title: str
    body: str | None = None
    appointment_id: str | None = None
    read_at: datetime | None = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    unread_count: int


class NotificationMarkReadResponse(BaseModel):
    updated: int
    unread_count: int


__all__ = [
    "NotificationListResponse",
    "NotificationMarkReadResponse",
    "NotificationResponse",
]
