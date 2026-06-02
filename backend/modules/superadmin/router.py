from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_global_admin
from modules.superadmin.repository import SuperAdminRepository
from modules.superadmin.schemas import (
    CouponCreate,
    CouponRedeemRequest,
    CouponRedemptionResponse,
    CouponResponse,
    CouponUpdate,
    GlobalAdminUpdate,
    PlanCreate,
    PlanResponse,
    PlanUpdate,
    StoreAdminCreate,
    StoreCreate,
    StoreGlobalResponse,
    StoreGlobalUpdate,
    StoreSubscriptionCreate,
    StoreSubscriptionResponse,
    UserGlobalResponse,
    UserGlobalUpdate,
)
from modules.users.model import User

router = APIRouter(prefix="/superadmin", tags=["SuperAdmin"])
PublicIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)]


def _store_response(store) -> StoreGlobalResponse:
    return StoreGlobalResponse(
        public_id=store.public_id,
        name=store.name,
        slug=store.slug,
        logo_url=store.logo_url,
        primary_color=store.primary_color,
        cancellation_hours=store.cancellation_hours,
        buffer_minutes=store.buffer_minutes,
        send_email_confirmation=store.send_email_confirmation,
        send_email_reminders=store.send_email_reminders,
        is_active=store.is_active,
        created_at=store.created_at,
        updated_at=store.updated_at,
    )


def _user_response(user) -> UserGlobalResponse:
    role = user.role.value if hasattr(user.role, "value") else user.role
    return UserGlobalResponse(
        public_id=user.public_id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
        role=role,
        store_id=user.store_id,
        is_active=user.is_active,
        is_global_admin=user.is_global_admin,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get("/stores", response_model=list[StoreGlobalResponse])
async def list_stores(
    search: str | None = Query(None, max_length=100),
    include_inactive: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    stores = await repo.list_stores(search, include_inactive, limit, offset)
    return [_store_response(store) for store in stores]


@router.post("/stores", response_model=StoreGlobalResponse, status_code=status.HTTP_201_CREATED)
async def create_store(
    data: StoreCreate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    try:
        store = await repo.create_store(data.model_dump(), actor)
        return _store_response(store)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/stores/{store_public_id}", response_model=StoreGlobalResponse)
async def get_store(
    store_public_id: PublicIdPath,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    store = await repo.get_store(store_public_id)
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    return _store_response(store)


@router.patch("/stores/{store_public_id}", response_model=StoreGlobalResponse)
async def update_store(
    store_public_id: PublicIdPath,
    data: StoreGlobalUpdate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    store = await repo.get_store(store_public_id)
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    try:
        updated = await repo.update_store(store, data.model_dump(exclude_unset=True), actor)
        return _store_response(updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/stores/{store_public_id}/admins", response_model=UserGlobalResponse, status_code=status.HTTP_201_CREATED)
async def create_store_admin(
    store_public_id: PublicIdPath,
    data: StoreAdminCreate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    store = await repo.get_store(store_public_id)
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    try:
        user = await repo.create_store_admin(store, data.model_dump(), actor)
        return _user_response(user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/stores/{store_public_id}/users", response_model=list[UserGlobalResponse])
async def list_store_users(
    store_public_id: PublicIdPath,
    include_inactive: bool = Query(False),
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    store = await repo.get_store(store_public_id)
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    users = await repo.list_store_users(store.id, include_inactive)
    return [_user_response(user) for user in users]


@router.patch("/users/{user_public_id}", response_model=UserGlobalResponse)
async def update_user(
    user_public_id: PublicIdPath,
    data: UserGlobalUpdate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    user = await repo.get_user(user_public_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    try:
        updated = await repo.update_user(user, data.model_dump(exclude_unset=True), actor)
        return _user_response(updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/users/{user_public_id}/global-admin", response_model=UserGlobalResponse)
async def set_global_admin(
    user_public_id: PublicIdPath,
    data: GlobalAdminUpdate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    user = await repo.get_user(user_public_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    try:
        updated = await repo.set_global_admin(user, data.is_global_admin, actor)
        return _user_response(updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(
    include_inactive: bool = Query(False),
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    return await repo.list_plans(include_inactive)


@router.post("/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(
    data: PlanCreate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    try:
        return await repo.create_plan(data.model_dump(), actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/plans/{plan_public_id}", response_model=PlanResponse)
async def update_plan(
    plan_public_id: PublicIdPath,
    data: PlanUpdate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    plan = await repo.get_plan(plan_public_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    try:
        return await repo.update_plan(plan, data.model_dump(exclude_unset=True), actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/stores/{store_public_id}/subscription", response_model=StoreSubscriptionResponse)
async def get_store_subscription(
    store_public_id: PublicIdPath,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    store = await repo.get_store(store_public_id)
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    subscription = await repo.get_store_subscription(store.id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")
    return subscription


@router.post("/stores/{store_public_id}/subscription", response_model=StoreSubscriptionResponse)
async def set_store_subscription(
    store_public_id: PublicIdPath,
    data: StoreSubscriptionCreate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    store = await repo.get_store(store_public_id)
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    plan = await repo.get_plan(data.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    return await repo.set_store_subscription(store, plan, data.model_dump(), actor)


@router.get("/coupons", response_model=list[CouponResponse])
async def list_coupons(
    include_inactive: bool = Query(False),
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    return await repo.list_coupons(include_inactive)


@router.post("/coupons", response_model=CouponResponse, status_code=status.HTTP_201_CREATED)
async def create_coupon(
    data: CouponCreate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    try:
        return await repo.create_coupon(data.model_dump(), actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/coupons/{coupon_public_id}", response_model=CouponResponse)
async def get_coupon(
    coupon_public_id: PublicIdPath,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    coupon = await repo.get_coupon(coupon_public_id)
    if not coupon:
        raise HTTPException(status_code=404, detail="Cupón no encontrado")
    return coupon


@router.patch("/coupons/{coupon_public_id}", response_model=CouponResponse)
async def update_coupon(
    coupon_public_id: PublicIdPath,
    data: CouponUpdate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    coupon = await repo.get_coupon(coupon_public_id)
    if not coupon:
        raise HTTPException(status_code=404, detail="Cupón no encontrado")
    try:
        return await repo.update_coupon(coupon, data.model_dump(exclude_unset=True), actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/stores/{store_public_id}/coupons/redeem", response_model=CouponRedemptionResponse)
async def redeem_store_coupon(
    store_public_id: PublicIdPath,
    data: CouponRedeemRequest,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    store = await repo.get_store(store_public_id)
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    subscription = await repo.get_store_subscription(store.id)
    if not subscription:
        raise HTTPException(status_code=404, detail="La tienda no tiene suscripción activa")
    coupon = await repo.get_coupon_by_code(data.coupon_code)
    if not coupon:
        raise HTTPException(status_code=404, detail="Cupón no encontrado")
    try:
        return await repo.redeem_coupon(store, subscription, coupon, actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/stores/{store_public_id}/coupon-redemptions", response_model=list[CouponRedemptionResponse])
async def list_store_redemptions(
    store_public_id: PublicIdPath,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = SuperAdminRepository(db)
    store = await repo.get_store(store_public_id)
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    return await repo.list_store_redemptions(store.id)