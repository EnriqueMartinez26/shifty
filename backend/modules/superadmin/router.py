from typing import Annotated

from fastapi import Depends, Path, Query, status
from core.router import CanonicalAPIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import (
    AppException,
    ResourceNotFoundException,
    StoreNotFoundException,
    UserNotFoundException,
)
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_global_admin
from modules.superadmin.repository import SuperAdminRepository
from modules.superadmin.schemas import (
    AppliedCouponSummary,
    AuditLogResponse,
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
    StoreOverviewResponse,
    StoreSubscriptionOverviewResponse,
    StoreGlobalUpdate,
    StoreSubscriptionCreate,
    StoreSubscriptionResponse,
    StoreTableResponse,
    StoreUsersOverviewResponse,
    UserGlobalResponse,
    UserGlobalUpdate,
)
from modules.stores.model import Store
from modules.users.model import User

router = CanonicalAPIRouter(prefix="/superadmin", tags=["SuperAdmin"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


def _store_response(store: Store) -> StoreGlobalResponse:
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


def _user_response(user: User) -> UserGlobalResponse:
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


@router.get("/stores", response_model=list[StoreTableResponse])
async def list_stores(
    search: str | None = Query(None, max_length=100),
    is_active: bool | None = Query(True),
    has_subscription: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> list[StoreTableResponse]:
    repo = SuperAdminRepository(db)
    stores = await repo.stores.list_stores(
        search, is_active, has_subscription, limit, offset
    )
    return [StoreTableResponse.model_validate(store) for store in stores]


@router.post(
    "/stores", response_model=StoreGlobalResponse, status_code=status.HTTP_201_CREATED
)
async def create_store(
    data: StoreCreate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> StoreGlobalResponse:
    repo = SuperAdminRepository(db)
    try:
        store = await repo.stores.create_store(data.model_dump(), actor)
        return _store_response(store)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.get("/stores/{store_public_id}", response_model=StoreGlobalResponse)
async def get_store(
    store_public_id: PublicIdPath,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> StoreGlobalResponse:
    repo = SuperAdminRepository(db)
    store = await repo.stores.get_store(store_public_id)
    if not store:
        raise StoreNotFoundException(identifier=store_public_id)
    return _store_response(store)


@router.get("/stores/{store_public_id}/overview", response_model=StoreOverviewResponse)
async def get_store_overview(
    store_public_id: PublicIdPath,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> StoreOverviewResponse:
    repo = SuperAdminRepository(db)
    overview = await repo.get_store_overview(store_public_id)
    if overview is None:
        raise StoreNotFoundException(identifier=store_public_id)

    admins = [_user_response(user) for user in overview["admins"]]
    users = [_user_response(user) for user in overview["users"]]
    subscription = overview["subscription"]
    coupon = overview["coupon"]

    subscription_response: StoreSubscriptionOverviewResponse | None = None
    if subscription is not None:
        applied_coupon = None
        if coupon is not None:
            applied_coupon = AppliedCouponSummary(
                public_id=coupon.public_id,
                code=coupon.code,
                coupon_type=coupon.coupon_type,
                value=coupon.value,
                currency=coupon.currency,
                is_active=coupon.is_active,
            )
        subscription_response = StoreSubscriptionOverviewResponse(
            public_id=subscription.public_id,
            store_id=subscription.store_id,
            plan_id=subscription.plan_id,
            status=subscription.status,
            base_amount=subscription.base_amount,
            discount_amount=subscription.discount_amount,
            total_amount=subscription.total_amount,
            currency=subscription.currency,
            current_period_start=subscription.current_period_start,
            current_period_end=subscription.current_period_end,
            coupon_id=subscription.coupon_id,
            is_active=subscription.is_active,
            created_at=subscription.created_at,
            updated_at=subscription.updated_at,
            plan_name=overview["plan_name"],
            billing_interval=overview["billing_interval"],
            max_staff=overview["max_staff"],
            max_services=overview["max_services"],
            applied_coupon=applied_coupon,
        )

    return StoreOverviewResponse(
        store=_store_response(overview["store"]),
        users=StoreUsersOverviewResponse(
            admins=admins,
            users=users,
            admins_count=overview["admins_count"],
            users_count=overview["users_count"],
            active_users_count=overview["active_users_count"],
        ),
        subscription=subscription_response,
        recent_redemptions=overview["recent_redemptions"],
    )


@router.get(
    "/stores/{store_public_id}/audit-logs", response_model=list[AuditLogResponse]
)
async def list_store_audit_logs(
    store_public_id: PublicIdPath,
    limit: int = Query(15, ge=1, le=50),
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogResponse]:
    repo = SuperAdminRepository(db)
    store = await repo.stores.get_store(store_public_id)
    if not store:
        raise StoreNotFoundException(identifier=store_public_id)
    logs = await repo.stores.list_store_audit_logs(store, limit)
    return [
        AuditLogResponse(
            public_id=str(log.id),
            created_at=log.created_at,
            actor_email=log.actor_email,
            resource_type=log.resource_type,
            action=log.action,
            payload_before=log.payload_before,
            payload_after=log.payload_after,
            context=log.context,
        )
        for log in logs
    ]


@router.patch("/stores/{store_public_id}", response_model=StoreGlobalResponse)
async def update_store(
    store_public_id: PublicIdPath,
    data: StoreGlobalUpdate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> StoreGlobalResponse:
    repo = SuperAdminRepository(db)
    store = await repo.stores.get_store(store_public_id)
    if not store:
        raise StoreNotFoundException(identifier=store_public_id)
    try:
        updated = await repo.stores.update_store(
            store, data.model_dump(exclude_unset=True), actor
        )
        return _store_response(updated)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.post(
    "/stores/{store_public_id}/admins",
    response_model=UserGlobalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_store_admin(
    store_public_id: PublicIdPath,
    data: StoreAdminCreate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> UserGlobalResponse:
    repo = SuperAdminRepository(db)
    store = await repo.stores.get_store(store_public_id)
    if not store:
        raise StoreNotFoundException(identifier=store_public_id)
    try:
        user = await repo.users.create_store_admin(store, data.model_dump(), actor)
        return _user_response(user)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.get("/stores/{store_public_id}/users", response_model=list[UserGlobalResponse])
async def list_store_users(
    store_public_id: PublicIdPath,
    include_inactive: bool = Query(False),
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> list[UserGlobalResponse]:
    repo = SuperAdminRepository(db)
    store = await repo.stores.get_store(store_public_id)
    if not store:
        raise StoreNotFoundException(identifier=store_public_id)
    users = await repo.users.list_store_users(store.id, include_inactive)
    return [_user_response(user) for user in users]


@router.patch("/users/{user_public_id}", response_model=UserGlobalResponse)
async def update_user(
    user_public_id: PublicIdPath,
    data: UserGlobalUpdate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> UserGlobalResponse:
    repo = SuperAdminRepository(db)
    user = await repo.users.get_user(user_public_id)
    if not user:
        raise UserNotFoundException(identifier=user_public_id)
    try:
        updated = await repo.users.update_user(
            user, data.model_dump(exclude_unset=True), actor
        )
        return _user_response(updated)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.patch("/users/{user_public_id}/global-admin", response_model=UserGlobalResponse)
async def set_global_admin(
    user_public_id: PublicIdPath,
    data: GlobalAdminUpdate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> UserGlobalResponse:
    repo = SuperAdminRepository(db)
    user = await repo.users.get_user(user_public_id)
    if not user:
        raise UserNotFoundException(identifier=user_public_id)
    try:
        updated = await repo.users.set_global_admin(user, data.is_global_admin, actor)
        return _user_response(updated)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(
    include_inactive: bool = Query(False),
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> list[PlanResponse]:
    repo = SuperAdminRepository(db)
    plans = await repo.plans.list_plans(include_inactive)
    return [PlanResponse.model_validate(plan) for plan in plans]


@router.post("/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(
    data: PlanCreate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> PlanResponse:
    repo = SuperAdminRepository(db)
    try:
        plan = await repo.plans.create_plan(data.model_dump(), actor)
        return PlanResponse.model_validate(plan)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.patch("/plans/{plan_public_id}", response_model=PlanResponse)
async def update_plan(
    plan_public_id: PublicIdPath,
    data: PlanUpdate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> PlanResponse:
    repo = SuperAdminRepository(db)
    plan = await repo.plans.get_plan(plan_public_id)
    if not plan:
        raise ResourceNotFoundException(resource="Plan", identifier=plan_public_id)
    try:
        updated = await repo.plans.update_plan(
            plan, data.model_dump(exclude_unset=True), actor
        )
        return PlanResponse.model_validate(updated)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.get(
    "/stores/{store_public_id}/subscription", response_model=StoreSubscriptionResponse
)
async def get_store_subscription(
    store_public_id: PublicIdPath,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> StoreSubscriptionResponse:
    repo = SuperAdminRepository(db)
    store = await repo.stores.get_store(store_public_id)
    if not store:
        raise ResourceNotFoundException(resource="Tienda", identifier=store_public_id)
    subscription = await repo.subscriptions.get_store_subscription(store.id)
    if not subscription:
        raise ResourceNotFoundException(
            resource="Suscripción", identifier=store_public_id
        )
    return StoreSubscriptionResponse.model_validate(subscription)


@router.post(
    "/stores/{store_public_id}/subscription", response_model=StoreSubscriptionResponse
)
async def set_store_subscription(
    store_public_id: PublicIdPath,
    data: StoreSubscriptionCreate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> StoreSubscriptionResponse:
    repo = SuperAdminRepository(db)
    store = await repo.stores.get_store(store_public_id)
    if not store:
        raise StoreNotFoundException(identifier=store_public_id)
    plan = await repo.plans.get_plan(data.plan_id)
    if not plan:
        raise ResourceNotFoundException(resource="Plan", identifier=data.plan_id)
    try:
        subscription = await repo.subscriptions.set_store_subscription(
            store, plan, data.model_dump(), actor
        )
        return StoreSubscriptionResponse.model_validate(subscription)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.get("/coupons", response_model=list[CouponResponse])
async def list_coupons(
    include_inactive: bool = Query(False),
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> list[CouponResponse]:
    repo = SuperAdminRepository(db)
    coupons = await repo.coupons.list_coupons(include_inactive)
    return [CouponResponse.model_validate(coupon) for coupon in coupons]


@router.post(
    "/coupons", response_model=CouponResponse, status_code=status.HTTP_201_CREATED
)
async def create_coupon(
    data: CouponCreate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> CouponResponse:
    repo = SuperAdminRepository(db)
    try:
        coupon = await repo.coupons.create_coupon(data.model_dump(), actor)
        return CouponResponse.model_validate(coupon)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.get("/coupons/{coupon_public_id}", response_model=CouponResponse)
async def get_coupon(
    coupon_public_id: PublicIdPath,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> CouponResponse:
    repo = SuperAdminRepository(db)
    coupon = await repo.coupons.get_coupon(coupon_public_id)
    if not coupon:
        raise ResourceNotFoundException(resource="Cupón", identifier=coupon_public_id)
    return CouponResponse.model_validate(coupon)


@router.patch("/coupons/{coupon_public_id}", response_model=CouponResponse)
async def update_coupon(
    coupon_public_id: PublicIdPath,
    data: CouponUpdate,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> CouponResponse:
    repo = SuperAdminRepository(db)
    coupon = await repo.coupons.get_coupon(coupon_public_id)
    if not coupon:
        raise ResourceNotFoundException(resource="Cupón", identifier=coupon_public_id)
    try:
        updated = await repo.coupons.update_coupon(
            coupon, data.model_dump(exclude_unset=True), actor
        )
        return CouponResponse.model_validate(updated)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.post(
    "/stores/{store_public_id}/coupons/redeem", response_model=CouponRedemptionResponse
)
async def redeem_store_coupon(
    store_public_id: PublicIdPath,
    data: CouponRedeemRequest,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> CouponRedemptionResponse:
    repo = SuperAdminRepository(db)
    store = await repo.stores.get_store(store_public_id)
    if not store:
        raise StoreNotFoundException(identifier=store_public_id)
    subscription = await repo.subscriptions.get_store_subscription(store.id)
    if not subscription:
        raise AppException(
            message="La tienda no tiene suscripción activa",
            http_status=404,
            error_code="SUBSCRIPTION_NOT_FOUND",
        )
    coupon = await repo.coupons.get_coupon_by_code(data.coupon_code)
    if not coupon:
        raise ResourceNotFoundException(resource="Cupón", identifier=data.coupon_code)
    try:
        redemption = await repo.coupons.redeem_coupon(
            store, subscription, coupon, actor
        )
        return CouponRedemptionResponse.model_validate(redemption)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.get(
    "/stores/{store_public_id}/coupon-redemptions",
    response_model=list[CouponRedemptionResponse],
)
async def list_store_redemptions(
    store_public_id: PublicIdPath,
    actor: User = Depends(get_current_global_admin),
    db: AsyncSession = Depends(get_db),
) -> list[CouponRedemptionResponse]:
    repo = SuperAdminRepository(db)
    store = await repo.stores.get_store(store_public_id)
    if not store:
        raise StoreNotFoundException(identifier=store_public_id)
    redemptions = await repo.coupons.list_store_redemptions(store.id)
    return [
        CouponRedemptionResponse.model_validate(redemption)
        for redemption in redemptions
    ]
