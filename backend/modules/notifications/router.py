from typing import Annotated

from fastapi import Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.router import CanonicalAPIRouter
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_staff
from modules.notifications.model import Notification
from modules.notifications.schemas import (
    NotificationListResponse,
    NotificationMarkReadResponse,
    NotificationResponse,
)
from modules.notifications.service import NotificationService
from modules.users.model import User

router = CanonicalAPIRouter(prefix="/notifications", tags=["Notifications"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


def _notification_response(notification: Notification) -> NotificationResponse:
    return NotificationResponse(
        public_id=notification.id,
        type=notification.type,
        title=notification.title,
        body=notification.body,
        appointment_id=notification.appointment_id,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    unread_only: bool = False,
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    items, unread_count = await NotificationService(db).list_for_store(
        user.store_id, limit=limit, unread_only=unread_only
    )
    return NotificationListResponse(
        items=[_notification_response(item) for item in items],
        unread_count=unread_count,
    )


@router.post("/{notification_id}/read", response_model=NotificationMarkReadResponse)
async def mark_notification_read(
    notification_id: PublicIdPath,
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> NotificationMarkReadResponse:
    result = await NotificationService(db).mark_read(notification_id, user.store_id)
    return NotificationMarkReadResponse(
        updated=result.updated, unread_count=result.unread_count
    )


@router.post("/read-all", response_model=NotificationMarkReadResponse)
async def mark_all_notifications_read(
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> NotificationMarkReadResponse:
    result = await NotificationService(db).mark_all_read(user.store_id)
    return NotificationMarkReadResponse(
        updated=result.updated, unread_count=result.unread_count
    )
