from typing import Annotated

from fastapi import Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import ResourceNotFoundException
from core.router import CanonicalAPIRouter
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_user
from modules.notifications.model import Notification
from modules.notifications.schemas import (
    NotificationListResponse,
    NotificationMarkReadResponse,
    NotificationResponse,
)
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


async def _unread_count(db: AsyncSession, store_id: str) -> int:
    total = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.store_id == store_id,
            Notification.read_at.is_(None),
            Notification.is_active.is_(True),
        )
    )
    return int(total or 0)


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    unread_only: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    filters = [
        Notification.store_id == user.store_id,
        Notification.is_active.is_(True),
    ]
    if unread_only:
        filters.append(Notification.read_at.is_(None))

    result = await db.execute(
        select(Notification)
        .where(*filters)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    return NotificationListResponse(
        items=[_notification_response(item) for item in result.scalars().all()],
        unread_count=await _unread_count(db, user.store_id),
    )


@router.post("/{notification_id}/read", response_model=NotificationMarkReadResponse)
async def mark_notification_read(
    notification_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationMarkReadResponse:
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.store_id == user.store_id,
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise ResourceNotFoundException(
            resource="Notificacion", identifier=notification_id
        )

    updated = 0 if notification.read_at else 1
    notification.mark_read()
    await db.commit()
    return NotificationMarkReadResponse(
        updated=updated,
        unread_count=await _unread_count(db, user.store_id),
    )


@router.post("/read-all", response_model=NotificationMarkReadResponse)
async def mark_all_notifications_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationMarkReadResponse:
    result = await db.execute(
        select(Notification).where(
            Notification.store_id == user.store_id,
            Notification.read_at.is_(None),
            Notification.is_active.is_(True),
        )
    )
    notifications = list(result.scalars().all())
    for notification in notifications:
        notification.mark_read()
    await db.commit()
    return NotificationMarkReadResponse(
        updated=len(notifications),
        unread_count=await _unread_count(db, user.store_id),
    )
