from datetime import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.feature_flags import merge_store_feature_flags, normalize_store_feature_flags
from modules.auth.dependencies import get_current_user
from modules.stores.model import Store, StoreSchedule
from modules.stores.schemas import (
    StoreFeatureFlagsResponse,
    StoreFeatureFlagsUpdate,
    StoreResponse,
    StoreUpdate,
)
from modules.users.model import User, UserRole

router = APIRouter(prefix="/stores", tags=["Stores"])


def _serialize_store(store: Store) -> StoreResponse:
    return StoreResponse(
        public_id=store.public_id,
        name=store.name,
        slug=store.slug,
        business_type=store.business_type,
        logo_url=store.logo_url,
        primary_color=store.primary_color,
        cover_url=store.cover_url,
        description=store.description,
        whatsapp_number=store.whatsapp_number,
        instagram_url=store.instagram_url,
        facebook_url=store.facebook_url,
        website_url=store.website_url,
        custom_client_fields=store.custom_client_fields,
        cancellation_hours=store.cancellation_hours,
        buffer_minutes=store.buffer_minutes,
        business_hours=store.business_hours,
        send_email_confirmation=store.send_email_confirmation,
        send_email_reminders=store.send_email_reminders,
        feature_flags=normalize_store_feature_flags(store.feature_flags),
    )


async def _get_current_store(user: User, db: AsyncSession) -> Store:
    result = await db.execute(select(Store).where(Store.id == user.store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    return store


def _replace_business_hours(store: Store, business_hours: dict | None) -> None:
    if business_hours is None:
        return

    days_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    store.schedules.clear()

    for day_key, periods in business_hours.items():
        day_of_week = days_map.get(day_key)
        if day_of_week is None or not periods:
            continue

        # The current table only supports one period per day without a destructive migration.
        period = periods[0]
        store.schedules.append(
            StoreSchedule(
                store_id=store.id,
                day_of_week=day_of_week,
                open_time=time.fromisoformat(period["open"]),
                close_time=time.fromisoformat(period["close"]),
            )
        )


@router.get("/me", response_model=StoreResponse)
async def get_my_store(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    store = await _get_current_store(user, db)
    return _serialize_store(store)


@router.patch("/me", response_model=StoreResponse)
async def update_my_store(
    data: StoreUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los administradores pueden cambiar la configuración",
        )

    store = await _get_current_store(user, db)
    update_data = data.model_dump(exclude_unset=True)

    if "slug" in update_data and update_data["slug"] != store.slug:
        slug_check = await db.execute(select(Store).where(Store.slug == update_data["slug"]))
        if slug_check.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="El slug ya está en uso")

    business_hours = update_data.pop("business_hours", None)
    theme_keys = (
        "business_type",
        "cover_url",
        "description",
        "whatsapp_number",
        "instagram_url",
        "facebook_url",
        "website_url",
        "custom_client_fields",
    )
    theme_config = dict(store.theme_config or {})
    for key in theme_keys:
        if key in update_data:
            theme_config[key] = update_data.pop(key)
    store.theme_config = theme_config

    for key, value in update_data.items():
        setattr(store, key, value)

    _replace_business_hours(store, business_hours)
    await db.commit()
    await db.refresh(store)
    return _serialize_store(store)


@router.get("/me/feature-flags", response_model=StoreFeatureFlagsResponse)
async def get_my_store_feature_flags(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    store = await _get_current_store(user, db)
    return StoreFeatureFlagsResponse(flags=normalize_store_feature_flags(store.feature_flags))


@router.put("/me/feature-flags", response_model=StoreFeatureFlagsResponse)
async def update_my_store_feature_flags(
    data: StoreFeatureFlagsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los administradores pueden cambiar la configuración",
        )

    store = await _get_current_store(user, db)
    store.feature_flags = merge_store_feature_flags(
        store.feature_flags,
        data.model_dump(exclude_unset=True),
    )
    await db.commit()
    await db.refresh(store)
    return StoreFeatureFlagsResponse(flags=normalize_store_feature_flags(store.feature_flags))
