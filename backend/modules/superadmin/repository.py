from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Row
from sqlalchemy.sql import Subquery
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.auth.service import normalize_email, revoke_sessions_for_user
from modules.audit.model import AuditAction, AuditLog
from modules.billing.model import CouponRedemption, Plan, SaaSCoupon, StoreSubscription
from modules.billing.subscription_rules import apply_subscription_transition
from modules.stores.model import Store
from modules.users.guards import (
    assert_deactivation_allowed,
    assert_global_admin_revocation_allowed,
)
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


# --- Resumen de tiendas para el listado del superadmin -----------------------
# Antes cada columna era una subconsulta correlacionada contra ``Store`` que la
# base evaluaba por fila: nueve por tienda, ~450 con el limite de 50 del router
# (B3-07, 2026-09-17). Ahora son tres subconsultas agregadas que se unen una
# sola vez. Se usa ``row_number()`` en lugar de ``DISTINCT ON``/``LATERAL``
# porque la suite de integracion corre sobre SQLite y necesita ser portable.

_ADMIN_ROLES = (UserRole.ADMIN.value,)


def _user_stats_subquery() -> Subquery:
    """Un ``GROUP BY store_id`` en lugar de tres conteos correlacionados."""
    es_admin = or_(User.role.in_(_ADMIN_ROLES), User.is_global_admin.is_(True))
    return (
        select(
            User.store_id.label("store_id"),
            func.count().label("users_count"),
            func.sum(case((User.is_active.is_(True), 1), else_=0)).label(
                "active_users_count"
            ),
            func.sum(case((es_admin, 1), else_=0)).label("admins_count"),
        )
        .where(User.store_id.is_not(None))
        .group_by(User.store_id)
        .subquery()
    )


def _latest_subscription_subquery() -> Subquery:
    """La suscripcion activa mas reciente por tienda, una sola vez.

    Antes eran tres subconsultas con el mismo ``ORDER BY created_at DESC
    LIMIT 1`` (estado, fin de periodo y nombre del plan) mas una cuarta que
    contaba para el filtro ``has_subscription``.
    """
    ranked = (
        select(
            StoreSubscription.store_id.label("store_id"),
            StoreSubscription.status.label("status"),
            StoreSubscription.plan_id.label("plan_id"),
            StoreSubscription.current_period_end.label("current_period_end"),
            func.row_number()
            .over(
                partition_by=StoreSubscription.store_id,
                order_by=StoreSubscription.created_at.desc(),
            )
            .label("rn"),
        )
        .where(StoreSubscription.is_active.is_(True))
        .subquery()
    )
    return select(ranked).where(ranked.c.rn == 1).subquery()


def _last_redemption_subquery() -> Subquery:
    return (
        select(
            CouponRedemption.store_id.label("store_id"),
            func.max(CouponRedemption.created_at).label("last_redemption_at"),
        )
        .group_by(CouponRedemption.store_id)
        .subquery()
    )


def _store_row(store: Store, row: Row[Any]) -> dict[str, Any]:
    return {
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
        "has_subscription": row.subscription_store_id is not None,
        "subscription_status": row.subscription_status,
        "current_plan_name": row.current_plan_name,
        "current_period_end": row.current_period_end,
        "last_redemption_at": row.last_redemption_at,
    }


def _assert_coupon_redeemable(
    coupon: SaaSCoupon,
    subscription: StoreSubscription,
    now: datetime,
    previous_redemption: CouponRedemption | None,
) -> None:
    """Elegibilidad de un canje: funcion pura sobre (cupon, suscripcion, ahora).

    Estaba embebida en ``redeem_coupon`` como ocho ``raise`` consecutivos
    detras de dos ``SELECT ... FOR UPDATE``, asi que no habia forma de probar
    la maquina de elegibilidad sin base (B3-07/B3-08, 2026-09-17). Corre
    DESPUES del lock: moverla antes reabriria la carrera de ``current_uses``.
    """
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
    if coupon.one_time_per_store and previous_redemption is not None:
        raise ValueError("Esta tienda ya canjeó ese cupón")


def _compute_discount(
    coupon: SaaSCoupon, base_amount: Decimal
) -> tuple[Decimal, Decimal]:
    """Descuento y total final; el descuento nunca supera la base."""
    if coupon.coupon_type == "percent":
        discount_amount = _money(base_amount * _money(coupon.value) / Decimal("100"))
    elif coupon.coupon_type == "fixed":
        discount_amount = _money(coupon.value)
    else:
        raise ValueError("Tipo de cupón inválido")
    discount_amount = min(discount_amount, base_amount)
    return discount_amount, _money(base_amount - discount_amount)


def _apply_patch(entity: Any, payload: dict[str, Any]) -> None:
    """Aplica un PATCH respetando el null explicito (B3-19, 2026-09-18).

    El router ya descarto lo que no vino (``model_dump(exclude_unset=True)``),
    asi que cada clave del payload es algo que el cliente mando. Un ``null``
    borra el valor si la columna admite NULL (logo, descripcion, vencimiento);
    en una columna NOT NULL se ignora como antes, en vez de terminar en 409.
    """
    columnas = sa_inspect(type(entity)).columns
    for key, value in payload.items():
        if value is None:
            columna = columnas.get(key)
            if columna is None or not columna.nullable:
                continue
        setattr(entity, key, value)


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
        *,
        store_id: str | None,
    ) -> None:
        # store_id es obligatorio (keyword) para que cada llamada decida a que
        # tienda pertenece la accion; None solo para lo global (B3-11).
        self.db.add(
            AuditLog(
                actor_id=actor.id,
                actor_public_id=actor.public_id,
                actor_email=actor.email,
                resource_type=resource_type,
                resource_id=resource_id,
                store_id=store_id,
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
        usuarios = _user_stats_subquery()
        suscripcion = _latest_subscription_subquery()
        canjes = _last_redemption_subquery()

        query = (
            select(
                Store,
                usuarios.c.admins_count,
                usuarios.c.users_count,
                usuarios.c.active_users_count,
                suscripcion.c.store_id.label("subscription_store_id"),
                suscripcion.c.status.label("subscription_status"),
                suscripcion.c.current_period_end,
                Plan.name.label("current_plan_name"),
                canjes.c.last_redemption_at,
            )
            .outerjoin(usuarios, usuarios.c.store_id == Store.id)
            .outerjoin(suscripcion, suscripcion.c.store_id == Store.id)
            .outerjoin(Plan, Plan.id == suscripcion.c.plan_id)
            .outerjoin(canjes, canjes.c.store_id == Store.id)
        )
        if is_active is not None:
            query = query.where(Store.is_active.is_(is_active))
        if search:
            pattern = f"%{search}%"
            query = query.where(
                (Store.name.ilike(pattern)) | (Store.slug.ilike(pattern))
            )
        if has_subscription is True:
            query = query.where(suscripcion.c.store_id.is_not(None))
        elif has_subscription is False:
            query = query.where(suscripcion.c.store_id.is_(None))
        query = query.order_by(Store.created_at.desc()).offset(offset).limit(limit)

        result = await self.db.execute(query)
        return [_store_row(row[0], row) for row in result.all()]

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
                store_id=store.id,
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
        _apply_patch(store, payload)
        try:
            await self.db.flush()
            self._audit(
                actor,
                "Store",
                store.public_id,
                AuditAction.UPDATE.value,
                store_id=store.id,
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
        # Filtro en SQL con LIMIT real (B3-11, regla 11). Antes se traian las
        # limit*4 entradas de superadmin de TODAS las tiendas y se filtraba en
        # Python: sin ninguna de esta tienda en esa ventana, el panel mostraba
        # "sin actividad" para una tienda que si la tuvo.
        result = await self.db.execute(
            select(AuditLog)
            .where(AuditLog.context == "superadmin", AuditLog.store_id == store.id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


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
        # El email se guarda normalizado (minusculas): el login matchea con
        # func.lower(email). La garantia de unicidad case-insensitive es el
        # indice funcional uq_users_email_lower; este pre-chequeo es solo el
        # mensaje amable (regla 16). Con limit(1) no puede dar 500 aunque la
        # base traiga duplicados heredados, y no se atrapa la IntegrityError:
        # en la carrera entre el SELECT y el INSERT decide el indice y main.py
        # responde 409 neutro (regla 20).
        data["email"] = normalize_email(str(data["email"]))
        existing = await self.db.execute(
            select(User.id).where(func.lower(User.email) == data["email"]).limit(1)
        )
        if existing.first() is not None:
            raise ValueError("Ya existe un usuario con ese email")
        user = User(
            **data,
            hashed_password=hash_password(password),
            full_name=f"{first_name} {last_name}".strip(),
            role=UserRole.ADMIN,
            store_id=store.id,
            is_global_admin=False,
        )
        self.db.add(user)
        await self.db.flush()
        self._audit(
            actor,
            "User",
            user.public_id,
            AuditAction.CREATE.value,
            store_id=user.store_id,
            after={"email": user.email, "store_id": store.id, "role": "admin"},
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_user(
        self, user: User, payload: dict[str, Any], actor: User
    ) -> User:
        data = payload.copy()
        password = data.pop("password", None)
        # Regla 14, en el unico lugar donde vive (AUD2-B3-01): la misma guarda
        # corre en PATCH /users/{id} y en DELETE /users/{id}.
        await assert_deactivation_allowed(
            self.db, actor, user, is_active=data.get("is_active")
        )
        before = {
            "role": user.role,
            "is_active": user.is_active,
            "is_global_admin": user.is_global_admin,
        }
        _apply_patch(user, data)
        if "first_name" in data or "last_name" in data:
            user.full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        if password:
            user.hashed_password = hash_password(password)
        if data.get("is_active") is False or data.get("role") is not None or password:
            await revoke_sessions_for_user(self.db, user.id)
        try:
            await self.db.flush()
            self._audit(
                actor,
                "User",
                user.public_id,
                AuditAction.UPDATE.value,
                store_id=user.store_id,
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
        # Regla 14, en el unico lugar donde vive (AUD2-B3-12): el conteo era
        # "leer y despues actuar" y aca tenia su cuarta copia. Revocar el flag
        # deja la plataforma sin SuperAdmin igual que desactivar la cuenta.
        if not enabled:
            await assert_global_admin_revocation_allowed(self.db, actor, user)
        before = {"is_global_admin": user.is_global_admin}
        user.is_global_admin = enabled
        if enabled:
            user.role = UserRole.ADMIN
            user.is_active = True
        # Cambiar el poder global exige re-login: las sesiones (y con ellas los
        # access tokens atados por sid) mueren aca mismo, en ambas direcciones.
        await revoke_sessions_for_user(self.db, user.id)
        await self.db.flush()
        self._audit(
            actor,
            "User",
            user.public_id,
            AuditAction.UPDATE.value,
            store_id=user.store_id,
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
                store_id=None,
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
        _apply_patch(plan, payload)
        try:
            await self.db.flush()
            self._audit(
                actor,
                "Plan",
                plan.public_id,
                AuditAction.UPDATE.value,
                store_id=None,
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
                plan_name=plan.name,
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
            subscription.plan_name = plan.name
            nuevo_estado = payload.get("status", subscription.status)
            if nuevo_estado != subscription.status:
                apply_subscription_transition(subscription, nuevo_estado)
            # Periodo nuevo: el aviso de vencimiento vuelve a estar disponible.
            if payload.get("current_period_end") is not None:
                subscription.expiry_warning_sent_at = None
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
            store_id=subscription.store_id,
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
                store_id=None,
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
        # coupon_type y value son NOT NULL: un null se ignora (_apply_patch),
        # asi que el candidato es el valor actual. Antes {"value": null}
        # llegaba aca como None y "None > 100" terminaba en 500.
        candidate_type = payload.get("coupon_type") or coupon.coupon_type
        candidate_value = (
            payload["value"] if payload.get("value") is not None else coupon.value
        )
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
        _apply_patch(coupon, payload)
        try:
            await self.db.flush()
            self._audit(
                actor,
                "SaaSCoupon",
                coupon.public_id,
                AuditAction.UPDATE.value,
                store_id=None,
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
        coupon = await self._lock_coupon(coupon.id)
        subscription = await self._lock_subscription(subscription.id)

        previous = await self._previous_redemption(coupon, store)
        _assert_coupon_redeemable(
            coupon, subscription, datetime.now(timezone.utc), previous
        )

        base_amount = _money(subscription.base_amount)
        discount_amount, final_amount = _compute_discount(coupon, base_amount)

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
            store_id=store.id,
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

    # populate_existing en los dos locks: el router ya cargo el cupon y la
    # suscripcion en esta sesion, y sin eso el FOR UPDATE devuelve la instancia
    # del identity map SIN refrescar: current_uses se validaba y se
    # incrementaba con el valor leido antes del lock y dos canjes concurrentes
    # pasaban el tope max_uses (S-08, 2026-09-18). Mismo patron que
    # payments/jobs.py.
    async def _lock_coupon(self, coupon_id: str) -> SaaSCoupon:
        result = await self.db.execute(
            select(SaaSCoupon)
            .where(SaaSCoupon.id == coupon_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one()

    async def _lock_subscription(self, subscription_id: str) -> StoreSubscription:
        result = await self.db.execute(
            select(StoreSubscription)
            .where(StoreSubscription.id == subscription_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one()

    async def _previous_redemption(
        self, coupon: SaaSCoupon, store: Store
    ) -> CouponRedemption | None:
        if not coupon.one_time_per_store:
            return None
        result = await self.db.execute(
            select(CouponRedemption).where(
                CouponRedemption.coupon_id == coupon.id,
                CouponRedemption.store_id == store.id,
                CouponRedemption.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

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
