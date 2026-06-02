from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.audit.model import AuditAction, AuditLog
from modules.billing.model import CouponRedemption, Plan, SaaSCoupon, StoreSubscription
from modules.stores.model import Store
from modules.users.model import User, UserRole


def _money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _json_safe(value):
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


class SuperAdminRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _audit(self, actor: User, resource_type: str, resource_id: str, action: str, before=None, after=None) -> None:
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

    async def list_stores(self, search: str | None, include_inactive: bool, limit: int, offset: int) -> list[Store]:
        query = select(Store)
        if not include_inactive:
            query = query.where(Store.is_active.is_(True))
        if search:
            pattern = f"%{search}%"
            query = query.where((Store.name.ilike(pattern)) | (Store.slug.ilike(pattern)))
        query = query.order_by(Store.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_store(self, public_id: str) -> Store | None:
        result = await self.db.execute(select(Store).where(Store.public_id == public_id))
        return result.scalar_one_or_none()

    async def create_store(self, payload: dict, actor: User) -> Store:
        store = Store(**payload)
        self.db.add(store)
        try:
            await self.db.flush()
            self._audit(actor, "Store", store.public_id, AuditAction.CREATE.value, after={"slug": store.slug, "name": store.name})
            await self.db.commit()
            await self.db.refresh(store)
            return store
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Ya existe una tienda con ese slug")

    async def update_store(self, store: Store, payload: dict, actor: User) -> Store:
        before = {"name": store.name, "slug": store.slug, "is_active": store.is_active}
        for key, value in payload.items():
            if value is not None:
                setattr(store, key, value)
        try:
            await self.db.flush()
            self._audit(actor, "Store", store.public_id, AuditAction.UPDATE.value, before=before, after=payload)
            await self.db.commit()
            await self.db.refresh(store)
            return store
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("No se pudo actualizar la tienda; revisá slug único y datos enviados")

    async def list_store_users(self, store_id: str, include_inactive: bool) -> list[User]:
        query = select(User).where(User.store_id == store_id)
        if not include_inactive:
            query = query.where(User.is_active.is_(True))
        query = query.order_by(User.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_user(self, public_id: str) -> User | None:
        result = await self.db.execute(select(User).where(User.id == public_id))
        return result.scalar_one_or_none()

    async def create_store_admin(self, store: Store, payload: dict, actor: User) -> User:
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
            self._audit(actor, "User", user.public_id, AuditAction.CREATE.value, after={"email": user.email, "store_id": store.id, "role": "admin"})
            await self.db.commit()
            await self.db.refresh(user)
            return user
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Ya existe un usuario con ese email")

    async def update_user(self, user: User, payload: dict, actor: User) -> User:
        data = payload.copy()
        password = data.pop("password", None)
        before = {"role": user.role, "is_active": user.is_active, "is_global_admin": user.is_global_admin}
        for key, value in data.items():
            if value is not None:
                setattr(user, key, value)
        if data.get("first_name") is not None or data.get("last_name") is not None:
            user.full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        if password:
            user.hashed_password = hash_password(password)
        try:
            await self.db.flush()
            self._audit(actor, "User", user.public_id, AuditAction.UPDATE.value, before=before, after=data)
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
                select(func.count()).select_from(User).where(
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
        self._audit(actor, "User", user.public_id, AuditAction.UPDATE.value, before=before, after={"is_global_admin": enabled})
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def list_plans(self, include_inactive: bool) -> list[Plan]:
        query = select(Plan)
        if not include_inactive:
            query = query.where(Plan.is_active.is_(True))
        result = await self.db.execute(query.order_by(Plan.created_at.desc()))
        return list(result.scalars().all())

    async def get_plan(self, public_id: str) -> Plan | None:
        result = await self.db.execute(select(Plan).where(Plan.id == public_id))
        return result.scalar_one_or_none()

    async def create_plan(self, payload: dict, actor: User) -> Plan:
        plan = Plan(**payload)
        self.db.add(plan)
        try:
            await self.db.flush()
            self._audit(actor, "Plan", plan.public_id, AuditAction.CREATE.value, after={"name": plan.name, "price": str(plan.price)})
            await self.db.commit()
            await self.db.refresh(plan)
            return plan
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Ya existe un plan con ese nombre")

    async def update_plan(self, plan: Plan, payload: dict, actor: User) -> Plan:
        before = {"name": plan.name, "price": str(plan.price), "is_active": plan.is_active}
        for key, value in payload.items():
            if value is not None:
                setattr(plan, key, value)
        try:
            await self.db.flush()
            self._audit(actor, "Plan", plan.public_id, AuditAction.UPDATE.value, before=before, after=payload)
            await self.db.commit()
            await self.db.refresh(plan)
            return plan
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("No se pudo actualizar el plan")

    async def get_store_subscription(self, store_id: str) -> StoreSubscription | None:
        result = await self.db.execute(
            select(StoreSubscription)
            .where(StoreSubscription.store_id == store_id, StoreSubscription.is_active.is_(True))
            .order_by(StoreSubscription.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def set_store_subscription(self, store: Store, plan: Plan, payload: dict, actor: User) -> StoreSubscription:
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
            before = {"plan_id": subscription.plan_id, "base_amount": str(subscription.base_amount), "total_amount": str(subscription.total_amount)}
            subscription.plan_id = plan.id
            subscription.status = payload.get("status", subscription.status)
            subscription.base_amount = base_amount
            subscription.discount_amount = Decimal("0.00")
            subscription.total_amount = base_amount
            subscription.currency = currency
            subscription.coupon_id = None
            subscription.current_period_start = payload.get("current_period_start", subscription.current_period_start)
            subscription.current_period_end = payload.get("current_period_end", subscription.current_period_end)
            action = AuditAction.UPDATE.value

        await self.db.flush()
        self._audit(actor, "StoreSubscription", subscription.public_id, action, before=before, after={"store_id": store.id, "plan_id": plan.id, "total_amount": str(subscription.total_amount)})
        await self.db.commit()
        await self.db.refresh(subscription)
        return subscription

    async def list_coupons(self, include_inactive: bool) -> list[SaaSCoupon]:
        query = select(SaaSCoupon)
        if not include_inactive:
            query = query.where(SaaSCoupon.is_active.is_(True))
        result = await self.db.execute(query.order_by(SaaSCoupon.created_at.desc()))
        return list(result.scalars().all())

    async def get_coupon(self, public_id: str) -> SaaSCoupon | None:
        result = await self.db.execute(select(SaaSCoupon).where(SaaSCoupon.id == public_id))
        return result.scalar_one_or_none()

    async def get_coupon_by_code(self, code: str) -> SaaSCoupon | None:
        result = await self.db.execute(select(SaaSCoupon).where(func.upper(SaaSCoupon.code) == code.upper()))
        return result.scalar_one_or_none()

    async def create_coupon(self, payload: dict, actor: User) -> SaaSCoupon:
        coupon = SaaSCoupon(**payload, created_by_id=actor.id)
        self.db.add(coupon)
        try:
            await self.db.flush()
            self._audit(actor, "SaaSCoupon", coupon.public_id, AuditAction.CREATE.value, after={"code": coupon.code, "type": coupon.coupon_type})
            await self.db.commit()
            await self.db.refresh(coupon)
            return coupon
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Ya existe un cupón con ese código")

    async def update_coupon(self, coupon: SaaSCoupon, payload: dict, actor: User) -> SaaSCoupon:
        before = {"code": coupon.code, "is_active": coupon.is_active, "current_uses": coupon.current_uses}
        candidate_type = payload.get("coupon_type", coupon.coupon_type)
        candidate_value = payload.get("value", coupon.value)
        candidate_valid_from = payload.get("valid_from", coupon.valid_from)
        candidate_valid_until = payload.get("valid_until", coupon.valid_until)
        if candidate_type == "percent" and candidate_value > 100:
            raise ValueError("El porcentaje de descuento no puede superar 100")
        if candidate_valid_from and candidate_valid_until and candidate_valid_from >= candidate_valid_until:
            raise ValueError("valid_from debe ser anterior a valid_until")
        for key, value in payload.items():
            if value is not None:
                setattr(coupon, key, value)
        try:
            await self.db.flush()
            self._audit(actor, "SaaSCoupon", coupon.public_id, AuditAction.UPDATE.value, before=before, after=payload)
            await self.db.commit()
            await self.db.refresh(coupon)
            return coupon
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("No se pudo actualizar el cupón")

    async def redeem_coupon(self, store: Store, subscription: StoreSubscription, coupon: SaaSCoupon, actor: User) -> CouponRedemption:
        coupon_result = await self.db.execute(
            select(SaaSCoupon).where(SaaSCoupon.id == coupon.id).with_for_update()
        )
        coupon = coupon_result.scalar_one()
        subscription_result = await self.db.execute(
            select(StoreSubscription).where(StoreSubscription.id == subscription.id).with_for_update()
        )
        subscription = subscription_result.scalar_one()

        now = datetime.now(timezone.utc)
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
            discount_amount = _money(base_amount * _money(coupon.value) / Decimal("100"))
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
        self._audit(actor, "CouponRedemption", redemption.public_id, AuditAction.CREATE.value, after={"store_id": store.id, "code": coupon.code, "discount_amount": str(discount_amount), "final_amount": str(final_amount)})
        await self.db.commit()
        await self.db.refresh(redemption)
        return redemption

    async def list_store_redemptions(self, store_id: str) -> list[CouponRedemption]:
        result = await self.db.execute(
            select(CouponRedemption)
            .where(CouponRedemption.store_id == store_id)
            .order_by(CouponRedemption.created_at.desc())
        )
        return list(result.scalars().all())