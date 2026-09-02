from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.audit.model import AuditAction, AuditLog
from modules.billing.model import CouponRedemption, Plan, SaaSCoupon, StoreSubscription
from modules.stores.model import Store
from modules.users.model import User, UserRole


def _money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


class _BaseAdminRepository:
    """Base de los repositorios de superadmin: sesión + auditoría común."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _audit(
        self,
        actor: User,
        resource_type: str,
        resource_id: str,
        action: str,
        before: Any = None,
        after: Any = None,
    ) -> None:
        self.db.add(
            AuditLog(
                actor_id=actor.id,
                actor_public_id=actor.public_id,
                actor_email=actor.email,
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                payload_before=_json_safe(before),
                payload_after=_json_safe(after),
                context="superadmin",
            )
        )


class StoreAdminRepository(_BaseAdminRepository):
    async def list_stores(
        self,
        search: str | None,
        is_active: bool | None,
        has_subscription: bool | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        admin_roles = (UserRole.ADMIN.value,)
        admins_count = (
            select(func.count())
            .select_from(User)
            .where(
                User.store_id == Store.id,
                or_(User.role.in_(admin_roles), User.is_global_admin.is_(True)),
            )
            .correlate(Store)
            .scalar_subquery()
        )
        users_count = (
            select(func.count())
            .select_from(User)
            .where(User.store_id == Store.id)
            .correlate(Store)
            .scalar_subquery()
        )
        active_users_count = (
            select(func.count())
            .select_from(User)
            .where(User.store_id == Store.id, User.is_active.is_(True))
            .correlate(Store)
            .scalar_subquery()
        )
        has_subscription_query = (
            select(func.count())
            .select_from(StoreSubscription)
            .where(
                StoreSubscription.store_id == Store.id,
                StoreSubscription.is_active.is_(True),
            )
            .correlate(Store)
            .scalar_subquery()
        )
        subscription_status = (
            select(StoreSubscription.status)
            .where(
                StoreSubscription.store_id == Store.id,
                StoreSubscription.is_active.is_(True),
            )
            .order_by(StoreSubscription.created_at.desc())
            .limit(1)
            .correlate(Store)
            .scalar_subquery()
        )
        current_period_end = (
            select(StoreSubscription.current_period_end)
            .where(
                StoreSubscription.store_id == Store.id,
                StoreSubscription.is_active.is_(True),
            )
            .order_by(StoreSubscription.created_at.desc())
            .limit(1)
            .correlate(Store)
            .scalar_subquery()
        )
        current_plan_name = (
            select(Plan.name)
            .join(StoreSubscription, Plan.id == StoreSubscription.plan_id)
            .where(
                StoreSubscription.store_id == Store.id,
                StoreSubscription.is_active.is_(True),
            )
            .order_by(StoreSubscription.created_at.desc())
            .limit(1)
            .correlate(Store)
            .scalar_subquery()
        )
        last_redemption_at = (
            select(func.max(CouponRedemption.created_at))
            .where(CouponRedemption.store_id == Store.id)
            .correlate(Store)
            .scalar_subquery()
        )

        query = select(
            Store,
            admins_count.label("admins_count"),
            users_count.label("users_count"),
            active_users_count.label("active_users_count"),
            has_subscription_query.label("has_subscription_count"),
            subscription_status.label("subscription_status"),
            current_plan_name.label("current_plan_name"),
            current_period_end.label("current_period_end"),
            last_redemption_at.label("last_redemption_at"),
        )
        if is_active is not None:
            query = query.where(Store.is_active.is_(is_active))
        if search:
            pattern = f"%{search}%"
            query = query.where(
                (Store.name.ilike(pattern)) | (Store.slug.ilike(pattern))
            )
        if has_subscription is True:
            query = query.where(has_subscription_query > 0)
        elif has_subscription is False:
            query = query.where(has_subscription_query == 0)
        query = query.order_by(Store.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        rows: list[dict[str, Any]] = []
        for row in result.all():
            store = row[0]
            rows.append(
                {
                    "public_id": store.public_id,
                    "name": store.name,
                    "slug": store.slug,
                    "logo_url": store.logo_url,
                    "primary_color": store.primary_color,
                    "cancellation_hours": store.cancellation_hours,
                    "buffer_minutes": store.buffer_minutes,
                    "send_email_confirmation": store.send_email_confirmation,
                    "send_email_reminders": store.send_email_reminders,
                    "is_active": store.is_active,
                    "created_at": store.created_at,
                    "updated_at": store.updated_at,
                    "admins_count": int(row.admins_count or 0),
                    "users_count": int(row.users_count or 0),
                    "active_users_count": int(row.active_users_count or 0),
                    "has_subscription": bool(row.has_subscription_count),
                    "subscription_status": row.subscription_status,
                    "current_plan_name": row.current_plan_name,
                    "current_period_end": row.current_period_end,
                    "last_redemption_at": row.last_redemption_at,
                }
            )
        return rows

    async def get_store(self, public_id: str) -> Store | None:
        result = await self.db.execute(
            select(Store).where(Store.public_id == public_id)
        )
        return result.scalar_one_or_none()

    async def create_store(self, payload: dict[str, Any], actor: User) -> Store:
        store = Store(**payload)
        store.public_id = store.id
        self.db.add(store)
        try:
            await self.db.flush()
            self._audit(
                actor,
                "Store",
                store.public_id,
                AuditAction.CREATE.value,
                after={"slug": store.slug, "name": store.name},
            )
            await self.db.commit()
            await self.db.refresh(store)
            return store
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Ya existe una tienda con ese slug")

    async def update_store(
        self, store: Store, payload: dict[str, Any], actor: User
    ) -> Store:
        before = {"name": store.name, "slug": store.slug, "is_active": store.is_active}
        for key, value in payload.items():
            if value is not None:
                setattr(store, key, value)
        try:
            await self.db.flush()
            self._audit(
                actor,
                "Store",
                store.public_id,
                AuditAction.UPDATE.value,
                before=before,
                after=payload,
            )
            await self.db.commit()
            await self.db.refresh(store)
            return store
        except IntegrityError:
            await self.db.rollback()
            raise ValueError(
                "No se pudo actualizar la tienda; revisá slug único y datos enviados"
            )

    async def list_store_audit_logs(self, store: Store, limit: int) -> list[AuditLog]:
        user_ids_result = await self.db.execute(
            select(User.id).where(User.store_id == store.id)
        )
        user_public_ids = set(user_ids_result.scalars().all())

        logs_result = await self.db.execute(
            select(AuditLog)
            .where(AuditLog.context == "superadmin")
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(max(limit * 4, limit))
        )
        logs = list(logs_result.scalars().all())

        relevant: list[AuditLog] = []
        for log in logs:
            payload_after = (
                log.payload_after if isinstance(log.payload_after, dict) else {}
            )
            payload_before = (
                log.payload_before if isinstance(log.payload_before, dict) else {}
            )
            linked_store_ids = {
                payload_after.get("store_id"),
                payload_before.get("store_id"),
            }
            is_store_log = (
                log.resource_type == "Store" and log.resource_id == store.public_id
            )
            is_user_log = (
                log.resource_type == "User" and log.resource_id in user_public_ids
            )
            is_store_scoped_payload = store.id in linked_store_ids
            if is_store_log or is_user_log or is_store_scoped_payload:
                relevant.append(log)
            if len(relevant) >= limit:
                break
        return relevant


class UserAdminRepository(_BaseAdminRepository):
    async def list_store_users(
        self, store_id: str, include_inactive: bool
    ) -> list[User]:
        query = select(User).where(User.store_id == store_id)
        if not include_inactive:
            query = query.where(User.is_active.is_(True))
        query = query.order_by(User.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_user(self, public_id: str) -> User | None:
        result = await self.db.execute(select(User).where(User.id == public_id))
        return result.scalar_one_or_none()

    async def create_store_admin(
        self, store: Store, payload: dict[str, Any], actor: User
    ) -> User:
        data = payload.copy()
        password = data.pop("password")
        first_name = data.get("first_name") or ""
        last_name = data.get("last_name") or ""
        user = User(
            **data,
            hashed_password=hash_password(password),
            full_name=f"{first_name} {last_name}".strip(),
            role=UserRole.ADMIN,
            store_id=store.id,
            is_global_admin=False,
        )
        self.db.add(user)
        try:
            await self.db.flush()
            self._audit(
                actor,
                "User",
                user.public_id,
                AuditAction.CREATE.value,
                after={"email": user.email, "store_id": store.id, "role": "admin"},
            )
            await self.db.commit()
            await self.db.refresh(user)
            return user
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Ya existe un usuario con ese email")

    async def update_user(
        self, user: User, payload: dict[str, Any], actor: User
    ) -> User:
        data = payload.copy()
        password = data.pop("password", None)
        before = {
            "role": user.role,
            "is_active": user.is_active,
            "is_global_admin": user.is_global_admin,
        }
        for key, value in data.items():
            if value is not None:
                setattr(user, key, value)
        if data.get("first_name") is not None or data.get("last_name") is not None:
            user.full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        if password:
            user.hashed_password = hash_password(password)
        try:
            await self.db.flush()
            self._audit(
                actor,
                "User",
                user.public_id,
                AuditAction.UPDATE.value,
                before=before,
                after=data,
            )
            await self.db.commit()
            await self.db.refresh(user)
            return user
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("No se pudo actualizar el usuario")

    async def set_global_admin(self, user: User, enabled: bool, actor: User) -> User:
        if not enabled and user.id == actor.id:
            raise ValueError("No podés revocar tu propio acceso SuperAdmin")
        if not enabled and user.is_global_admin:
            result = await self.db.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.is_active.is_(True),
                    User.is_global_admin.is_(True),
                )
            )
            if int(result.scalar_one()) <= 1:
                raise ValueError("No se puede revocar el último SuperAdmin activo")
        before = {"is_global_admin": user.is_global_admin}
        user.is_global_admin = enabled
        if enabled:
            user.role = UserRole.ADMIN
            user.is_active = True
        await self.db.flush()
        self._audit(
            actor,
            "User",
            user.public_id,
            AuditAction.UPDATE.value,
            before=before,
            after={"is_global_admin": enabled},
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user


class PlanAdminRepository(_BaseAdminRepository):
    async def list_plans(self, include_inactive: bool) -> list[Plan]:
        query = select(Plan)
        if not include_inactive:
            query = query.where(Plan.is_active.is_(True))
        result = await self.db.execute(query.order_by(Plan.created_at.desc()))
        return list(result.scalars().all())

    async def get_plan(self, public_id: str) -> Plan | None:
        result = await self.db.execute(select(Plan).where(Plan.id == public_id))
        return result.scalar_one_or_none()

    async def create_plan(self, payload: dict[str, Any], actor: User) -> Plan:
        plan = Plan(**payload)
        self.db.add(plan)
        try:
            await self.db.flush()
            self._audit(
                actor,
                "Plan",
                plan.public_id,
                AuditAction.CREATE.value,
                after={"name": plan.name, "price": str(plan.price)},
            )
            await self.db.commit()
            await self.db.refresh(plan)
            return plan
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Ya existe un plan con ese nombre")

    async def update_plan(
        self, plan: Plan, payload: dict[str, Any], actor: User
    ) -> Plan:
        before = {
            "name": plan.name,
            "price": str(plan.price),
            "is_active": plan.is_active,
        }
        for key, value in payload.items():
            if value is not None:
                setattr(plan, key, value)
        try:
            await self.db.flush()
            self._audit(
                actor,
                "Plan",
                plan.public_id,
                AuditAction.UPDATE.value,
                before=before,
                after=payload,
            )
            await self.db.commit()
            await self.db.refresh(plan)
            return plan
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("No se pudo actualizar el plan")


class SubscriptionAdminRepository(_BaseAdminRepository):
    async def get_store_subscription(self, store_id: str) -> StoreSubscription | None:
        result = await self.db.execute(
            select(StoreSubscription)
            .where(
                StoreSubscription.store_id == store_id,
                StoreSubscription.is_active.is_(True),
            )
            .order_by(StoreSubscription.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def set_store_subscription(
        self, store: Store, plan: Plan, payload: dict[str, Any], actor: User
    ) -> StoreSubscription:
        if not store.is_active:
            raise ValueError(
                "No se puede asignar una suscripción a una tienda inactiva"
            )
        subscription = await self.get_store_subscription(store.id)
        base_amount = _money(payload.get("base_amount") or plan.price)
        currency = payload.get("currency") or plan.currency
        if subscription is None:
            subscription = StoreSubscription(
                store_id=store.id,
                plan_id=plan.id,
                status=payload.get("status", "active"),
                base_amount=base_amount,
                discount_amount=Decimal("0.00"),
                total_amount=base_amount,
                currency=currency,
                current_period_start=payload.get("current_period_start"),
                current_period_end=payload.get("current_period_end"),
            )
            self.db.add(subscription)
            action = AuditAction.CREATE.value
            before = None
        else:
            before = {
                "plan_id": subscription.plan_id,
                "base_amount": str(subscription.base_amount),
                "total_amount": str(subscription.total_amount),
            }
            subscription.plan_id = plan.id
            subscription.status = payload.get("status", subscription.status)
            subscription.base_amount = base_amount
            subscription.discount_amount = Decimal("0.00")
            subscription.total_amount = base_amount
            subscription.currency = currency
            subscription.coupon_id = None
            subscription.current_period_start = payload.get(
                "current_period_start", subscription.current_period_start
            )
            subscription.current_period_end = payload.get(
                "current_period_end", subscription.current_period_end
            )
            action = AuditAction.UPDATE.value

        await self.db.flush()
        self._audit(
            actor,
            "StoreSubscription",
            subscription.public_id,
            action,
            before=before,
            after={
                "store_id": store.id,
                "plan_id": plan.id,
                "total_amount": str(subscription.total_amount),
            },
        )
        await self.db.commit()
        await self.db.refresh(subscription)
        return subscription


class CouponAdminRepository(_BaseAdminRepository):
    async def list_coupons(self, include_inactive: bool) -> list[SaaSCoupon]:
        query = select(SaaSCoupon)
        if not include_inactive:
            query = query.where(SaaSCoupon.is_active.is_(True))
        result = await self.db.execute(query.order_by(SaaSCoupon.created_at.desc()))
        return list(result.scalars().all())

    async def get_coupon(self, public_id: str) -> SaaSCoupon | None:
        result = await self.db.execute(
            select(SaaSCoupon).where(SaaSCoupon.id == public_id)
        )
        return result.scalar_one_or_none()

    async def get_coupon_by_code(self, code: str) -> SaaSCoupon | None:
        result = await self.db.execute(
            select(SaaSCoupon).where(func.upper(SaaSCoupon.code) == code.upper())
        )
        return result.scalar_one_or_none()

    async def create_coupon(self, payload: dict[str, Any], actor: User) -> SaaSCoupon:
        coupon = SaaSCoupon(**payload, created_by_id=actor.id)
        self.db.add(coupon)
        try:
            await self.db.flush()
            self._audit(
                actor,
                "SaaSCoupon",
                coupon.public_id,
                AuditAction.CREATE.value,
                after={"code": coupon.code, "type": coupon.coupon_type},
            )
            await self.db.commit()
            await self.db.refresh(coupon)
            return coupon
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Ya existe un cupón con ese código")

    async def update_coupon(
        self, coupon: SaaSCoupon, payload: dict[str, Any], actor: User
    ) -> SaaSCoupon:
        before = {
            "code": coupon.code,
            "is_active": coupon.is_active,
            "current_uses": coupon.current_uses,
        }
        candidate_type = payload.get("coupon_type", coupon.coupon_type)
        candidate_value = payload.get("value", coupon.value)
        candidate_valid_from = payload.get("valid_from", coupon.valid_from)
        candidate_valid_until = payload.get("valid_until", coupon.valid_until)
        if candidate_type == "percent" and candidate_value > 100:
            raise ValueError("El porcentaje de descuento no puede superar 100")
        if (
            candidate_valid_from
            and candidate_valid_until
            and candidate_valid_from >= candidate_valid_until
        ):
            raise ValueError("valid_from debe ser anterior a valid_until")
        for key, value in payload.items():
            if value is not None:
                setattr(coupon, key, value)
        try:
            await self.db.flush()
            self._audit(
                actor,
                "SaaSCoupon",
                coupon.public_id,
                AuditAction.UPDATE.value,
                before=before,
                after=payload,
            )
            await self.db.commit()
            await self.db.refresh(coupon)
            return coupon
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("No se pudo actualizar el cupón")

    async def redeem_coupon(
        self,
        store: Store,
        subscription: StoreSubscription,
        coupon: SaaSCoupon,
        actor: User,
    ) -> CouponRedemption:
        if not store.is_active:
            raise ValueError("No se puede canjear un cupón sobre una tienda inactiva")
        coupon_result = await self.db.execute(
            select(SaaSCoupon).where(SaaSCoupon.id == coupon.id).with_for_update()
        )
        coupon = coupon_result.scalar_one()
        subscription_result = await self.db.execute(
            select(StoreSubscription)
            .where(StoreSubscription.id == subscription.id)
            .with_for_update()
        )
        subscription = subscription_result.scalar_one()

        now = datetime.now(timezone.utc)
        period_end = _utc(subscription.current_period_end)
        if subscription.status != "active":
            raise ValueError("La suscripción de la tienda no está activa")
        if period_end and period_end < now:
            raise ValueError("La suscripción de la tienda está vencida")
        if not coupon.is_active:
            raise ValueError("El cupón no está activo")
        if coupon.valid_from and coupon.valid_from > now:
            raise ValueError("El cupón todavía no está vigente")
        if coupon.valid_until and coupon.valid_until < now:
            raise ValueError("El cupón está vencido")
        if coupon.max_uses is not None and coupon.current_uses >= coupon.max_uses:
            raise ValueError("El cupón ya alcanzó su límite de usos")
        if coupon.currency and coupon.currency != subscription.currency:
            raise ValueError("La moneda del cupón no coincide con la suscripción")
        if coupon.one_time_per_store:
            previous = await self.db.execute(
                select(CouponRedemption).where(
                    CouponRedemption.coupon_id == coupon.id,
                    CouponRedemption.store_id == store.id,
                    CouponRedemption.is_active.is_(True),
                )
            )
            if previous.scalar_one_or_none():
                raise ValueError("Esta tienda ya canjeó ese cupón")

        base_amount = _money(subscription.base_amount)
        if coupon.coupon_type == "percent":
            discount_amount = _money(
                base_amount * _money(coupon.value) / Decimal("100")
            )
        elif coupon.coupon_type == "fixed":
            discount_amount = _money(coupon.value)
        else:
            raise ValueError("Tipo de cupón inválido")

        discount_amount = min(discount_amount, base_amount)
        final_amount = _money(base_amount - discount_amount)

        coupon.current_uses += 1
        subscription.coupon_id = coupon.id
        subscription.discount_amount = discount_amount
        subscription.total_amount = final_amount

        redemption = CouponRedemption(
            coupon_id=coupon.id,
            store_id=store.id,
            subscription_id=subscription.id,
            redeemed_by_id=actor.id,
            code_snapshot=coupon.code,
            coupon_type_snapshot=coupon.coupon_type,
            value_snapshot=coupon.value,
            base_amount=base_amount,
            discount_amount=discount_amount,
            final_amount=final_amount,
            currency=subscription.currency,
        )
        self.db.add(redemption)
        await self.db.flush()
        self._audit(
            actor,
            "CouponRedemption",
            redemption.public_id,
            AuditAction.CREATE.value,
            after={
                "store_id": store.id,
                "code": coupon.code,
                "discount_amount": str(discount_amount),
                "final_amount": str(final_amount),
            },
        )
        await self.db.commit()
        await self.db.refresh(redemption)
        return redemption

    async def list_store_redemptions(
        self, store_id: str, limit: int | None = None
    ) -> list[CouponRedemption]:
        query = (
            select(CouponRedemption)
            .where(CouponRedemption.store_id == store_id)
            .order_by(CouponRedemption.created_at.desc())
        )
        if limit is not None:
            query = query.limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())


class SuperAdminRepository:
    """Fachada de los repositorios de superadmin, agrupados por agregado.

    Cada sub-repo tiene una sola razon para cambiar (SRP). El overview compone
    varios agregados a la vez, asi que vive en la fachada y no en un sub-repo.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.stores = StoreAdminRepository(db)
        self.users = UserAdminRepository(db)
        self.plans = PlanAdminRepository(db)
        self.subscriptions = SubscriptionAdminRepository(db)
        self.coupons = CouponAdminRepository(db)

    async def get_store_overview(self, public_id: str) -> dict[str, Any] | None:
        store = await self.stores.get_store(public_id)
        if store is None:
            return None

        users = await self.users.list_store_users(store.id, include_inactive=True)
        admins = [
            user
            for user in users
            if user.is_global_admin or str(user.role) == UserRole.ADMIN.value
        ]
        subscription = await self.subscriptions.get_store_subscription(store.id)
        plan = (
            await self.db.get(Plan, subscription.plan_id)
            if subscription is not None
            else None
        )
        coupon = (
            await self.db.get(SaaSCoupon, subscription.coupon_id)
            if subscription and subscription.coupon_id
            else None
        )

        return {
            "store": store,
            "admins": admins,
            "users": users,
            "admins_count": len(admins),
            "users_count": len(users),
            "active_users_count": sum(1 for user in users if user.is_active),
            "subscription": subscription,
            "plan_name": getattr(plan, "name", None),
            "billing_interval": getattr(plan, "billing_interval", None),
            "max_staff": getattr(plan, "max_staff", None),
            "max_services": getattr(plan, "max_services", None),
            "coupon": coupon,
            "recent_redemptions": await self.coupons.list_store_redemptions(
                store.id, limit=5
            ),
        }
