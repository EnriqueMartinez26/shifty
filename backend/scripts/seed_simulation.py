import asyncio
import os
import random
import secrets
import sys
from collections.abc import Sequence
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

load_dotenv(backend_dir.parent / ".env")

from core.security import hash_password
from modules.appointments.model import Appointment
from modules.audit.model import AuditAction, AuditLog
from modules.budget.model import Budget
from modules.billing.model import (
    CouponRedemption,
    SaaSCoupon,
    StoreSubscription,
)
from modules.ledger.model import CustomerLedger
from modules.payments.model import (
    OutboxMessage,
    Payment,
    PaymentGatewayConfig,
    WebhookInbox,
)
from modules.promotions.model import PromotionRedemption, StorePromotion
from modules.services.model import Service
from modules.staff.model import Schedule, Staff, StaffBlock, staff_services
from modules.stores.model import Store, StoreSchedule
from modules.users.model import User, UserRole
from modules.auth.session_model import AuthSession


DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not defined.")
DATABASE_URL = str(DATABASE_URL)

def _seed_password(role: str) -> str:
    """Sin credenciales quemadas en el repo: o vienen por env, o se generan
    aleatorias y se imprimen una unica vez. Un seed con 'admin123' que toque
    staging es una cuenta admin publica."""
    env_value = os.environ.get(f"SEED_PASSWORD_{role.upper()}")
    if env_value:
        return env_value
    generated = secrets.token_urlsafe(12) + "9a"
    print(f"[seed] password {role}: {generated}")
    return generated


PASSWORDS = {
    "global_admin": _seed_password("global_admin"),
    "admin": _seed_password("admin"),
    "staff": _seed_password("staff"),
    "client": _seed_password("client"),
}

SIMULATION_CONTEXT_PREFIX = "simulation:v2"
UTC = timezone.utc
NOW = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
RNG = random.Random(20260529)


STORE_SCENARIOS = [
    {
        "slug": "barberia-sentinel",
        "name": "Barberia Sentinel",
        "primary_color": "#1d4ed8",
        "theme_config": {"theme": "urban", "accent": "steel"},
        "requires_deposit": True,
        "deposit_percentage": 20,
        "cancellation_hours": 6,
        "min_booking_notice_hours": 2,
        "buffer_minutes": 10,
        "admin": {
            "email": "admin@barberia-sentinel.com",
            "first_name": "Master",
            "last_name": "Sentinel",
            "full_name": "Master Sentinel",
            "phone": "+54 11 5000-1001",
        },
        "hours": {
            0: (time(9, 0), time(20, 0)),
            1: (time(9, 0), time(20, 0)),
            2: (time(9, 0), time(20, 0)),
            3: (time(9, 0), time(20, 0)),
            4: (time(9, 0), time(21, 0)),
            5: (time(10, 0), time(19, 0)),
            6: (time(11, 0), time(16, 0)),
        },
        "services": [
            {
                "name": "Corte Moderno",
                "price": 1500,
                "duration": 30,
                "color": "#2563eb",
                "description": "Corte urbano con terminacion prolija.",
            },
            {
                "name": "Barba y Perfilado",
                "price": 900,
                "duration": 20,
                "color": "#0f766e",
                "description": "Perfilado de barba con toalla caliente.",
            },
            {
                "name": "Servicio VIP Completo",
                "price": 3200,
                "duration": 60,
                "color": "#b45309",
                "description": "Corte, barba, lavado y styling premium.",
            },
            {
                "name": "Skin Fade Premium",
                "price": 2100,
                "duration": 45,
                "color": "#7c3aed",
                "description": "Fade detallado con terminacion a navaja.",
            },
        ],
        "staff": [
            {
                "first_name": "Carlos",
                "last_name": "Barber",
                "display_name": "Carlos Barber",
                "email": "carlos.barber@shifty.com",
                "phone": "+54 11 5000-2001",
                "service_names": [
                    "Corte Moderno",
                    "Barba y Perfilado",
                    "Skin Fade Premium",
                ],
                "hours": {0: (9, 18), 1: (9, 18), 2: (9, 18), 3: (9, 18), 4: (10, 19)},
                "blocks": [
                    {
                        "days_from_now": 2,
                        "start_hour": 13,
                        "duration_hours": 2,
                        "reason": "training",
                    },
                ],
            },
            {
                "first_name": "Elena",
                "last_name": "Stylist",
                "display_name": "Elena Stylist",
                "email": "elena.stylist@shifty.com",
                "phone": "+54 11 5000-2002",
                "service_names": ["Corte Moderno", "Servicio VIP Completo"],
                "hours": {
                    0: (11, 19),
                    1: (11, 19),
                    2: (11, 19),
                    3: (11, 19),
                    5: (10, 16),
                },
                "blocks": [
                    {
                        "days_from_now": 4,
                        "start_hour": 15,
                        "duration_hours": 3,
                        "reason": "personal",
                    },
                ],
            },
            {
                "first_name": "Mateo",
                "last_name": "Rios",
                "display_name": "Mateo Rios",
                "email": "mateo.rios@shifty.com",
                "phone": "+54 11 5000-2003",
                "service_names": ["Barba y Perfilado", "Servicio VIP Completo"],
                "hours": {
                    1: (12, 20),
                    2: (12, 20),
                    3: (12, 20),
                    4: (12, 20),
                    6: (11, 16),
                },
                "blocks": [],
            },
        ],
        "clients": [
            {
                "email": "bruno.lopez@example.com",
                "first_name": "Bruno",
                "last_name": "Lopez",
                "phone": "+54 11 6000-3001",
            },
            {
                "email": "camila.rossi@example.com",
                "first_name": "Camila",
                "last_name": "Rossi",
                "phone": "+54 11 6000-3002",
            },
            {
                "email": "diego.mendez@example.com",
                "first_name": "Diego",
                "last_name": "Mendez",
                "phone": "+54 11 6000-3003",
            },
            {
                "email": "florencia.suarez@example.com",
                "first_name": "Florencia",
                "last_name": "Suarez",
                "phone": "+54 11 6000-3004",
            },
        ],
        "budgets": [
            {
                "title": "Campana Invierno Barberia",
                "improvement_description": "Landing de promos, automatizacion de recordatorios y ajuste de agenda.",
                "estimated_hours": 18,
                "hourly_rate": 22000,
                "status": "approved",
                "notes": "Prioridad alta por temporada de invierno.",
            },
            {
                "title": "Optimizacion de Checkout",
                "improvement_description": "Reserva publica con menos pasos y mejor recupero de pagos.",
                "estimated_hours": 24,
                "hourly_rate": 24000,
                "status": "draft",
                "notes": "Esperando feedback del admin del local.",
            },
        ],
    },
    {
        "slug": "salon-sentinel",
        "name": "Salon Sentinel",
        "primary_color": "#be185d",
        "theme_config": {"theme": "studio", "accent": "rose"},
        "requires_deposit": False,
        "deposit_percentage": 0,
        "cancellation_hours": 12,
        "min_booking_notice_hours": 4,
        "buffer_minutes": 15,
        "admin": {
            "email": "admin@salon-sentinel.com",
            "first_name": "Valeria",
            "last_name": "Sentinel",
            "full_name": "Valeria Sentinel",
            "phone": "+54 11 5000-1010",
        },
        "hours": {
            0: (time(10, 0), time(19, 0)),
            1: (time(10, 0), time(19, 0)),
            2: (time(10, 0), time(19, 0)),
            3: (time(10, 0), time(19, 0)),
            4: (time(10, 0), time(20, 0)),
            5: (time(9, 0), time(18, 0)),
        },
        "services": [
            {
                "name": "Color Completo",
                "price": 8500,
                "duration": 120,
                "color": "#db2777",
                "description": "Coloracion integral con diagnostico previo.",
            },
            {
                "name": "Corte y Brushing",
                "price": 4200,
                "duration": 60,
                "color": "#f97316",
                "description": "Corte femenino con brushing final.",
            },
            {
                "name": "Tratamiento Capilar",
                "price": 5600,
                "duration": 75,
                "color": "#059669",
                "description": "Nutricion profunda y sellado de fibra.",
            },
        ],
        "staff": [
            {
                "first_name": "Julieta",
                "last_name": "Color",
                "display_name": "Julieta Color",
                "email": "julieta.color@shifty.com",
                "phone": "+54 11 5000-2101",
                "service_names": ["Color Completo", "Tratamiento Capilar"],
                "hours": {
                    0: (10, 18),
                    1: (10, 18),
                    2: (10, 18),
                    4: (12, 20),
                    5: (9, 15),
                },
                "blocks": [
                    {
                        "days_from_now": 3,
                        "start_hour": 10,
                        "duration_hours": 4,
                        "reason": "vacation",
                    },
                ],
            },
            {
                "first_name": "Lucia",
                "last_name": "Brush",
                "display_name": "Lucia Brush",
                "email": "lucia.brush@shifty.com",
                "phone": "+54 11 5000-2102",
                "service_names": ["Corte y Brushing", "Tratamiento Capilar"],
                "hours": {
                    1: (11, 19),
                    2: (11, 19),
                    3: (11, 19),
                    4: (11, 19),
                    5: (10, 16),
                },
                "blocks": [],
            },
        ],
        "clients": [
            {
                "email": "nora.vera@example.com",
                "first_name": "Nora",
                "last_name": "Vera",
                "phone": "+54 11 6000-4001",
            },
            {
                "email": "paula.luna@example.com",
                "first_name": "Paula",
                "last_name": "Luna",
                "phone": "+54 11 6000-4002",
            },
            {
                "email": "romina.paz@example.com",
                "first_name": "Romina",
                "last_name": "Paz",
                "phone": "+54 11 6000-4003",
            },
        ],
        "budgets": [
            {
                "title": "Programa Fidelizacion Salon",
                "improvement_description": "Bonos por recurrencia, gift cards y referidos.",
                "estimated_hours": 20,
                "hourly_rate": 23000,
                "status": "approved",
                "notes": "Se implementa en dos etapas.",
            },
        ],
    },
]

SIMULATION_STORE_SLUGS = {scenario["slug"] for scenario in STORE_SCENARIOS}


async def get_by(session: AsyncSession, model: Any, *filters: Any) -> Any | None:
    result = await session.execute(select(model).where(*filters))
    return result.scalar_one_or_none()


async def cleanup_seed(session: AsyncSession) -> None:
    store_rows = await session.execute(
        select(Store.id).where(Store.slug.in_(SIMULATION_STORE_SLUGS))
    )
    store_ids = [row[0] for row in store_rows.fetchall()]
    if not store_ids:
        return

    appointment_rows = await session.execute(
        select(Appointment.id).where(
            Appointment.store_id.in_(store_ids),
            Appointment.idempotency_key.like(f"{SIMULATION_CONTEXT_PREFIX}:%"),
        )
    )
    appointment_ids = [row[0] for row in appointment_rows.fetchall()]

    staff_rows = await session.execute(
        select(Staff.id).where(Staff.store_id.in_(store_ids))
    )
    staff_ids = [row[0] for row in staff_rows.fetchall()]

    user_rows = await session.execute(
        select(User.id).where(User.store_id.in_(store_ids))
    )
    user_ids = [row[0] for row in user_rows.fetchall()]

    service_rows = await session.execute(
        select(Service.id).where(Service.store_id.in_(store_ids))
    )
    service_ids = [row[0] for row in service_rows.fetchall()]

    await session.execute(
        delete(AuditLog).where(AuditLog.context.like(f"{SIMULATION_CONTEXT_PREFIX}:%"))
    )
    if user_ids:
        await session.execute(delete(AuditLog).where(AuditLog.actor_id.in_(user_ids)))
        await session.execute(
            delete(SaaSCoupon).where(SaaSCoupon.created_by_id.in_(user_ids))
        )

    if appointment_ids:
        await session.execute(
            delete(Payment).where(Payment.appointment_id.in_(appointment_ids))
        )
        await session.execute(
            delete(CustomerLedger).where(
                CustomerLedger.appointment_id.in_(appointment_ids)
            )
        )
        await session.execute(
            delete(PromotionRedemption).where(
                PromotionRedemption.appointment_id.in_(appointment_ids)
            )
        )
        await session.execute(
            delete(CouponRedemption).where(
                CouponRedemption.subscription_id.in_(
                    select(StoreSubscription.id).where(
                        StoreSubscription.store_id.in_(store_ids)
                    )
                )
            )
        )
        await session.execute(
            delete(Appointment).where(Appointment.id.in_(appointment_ids))
        )

    if staff_ids:
        await session.execute(
            delete(StaffBlock).where(StaffBlock.staff_id.in_(staff_ids))
        )
        await session.execute(delete(Schedule).where(Schedule.staff_id.in_(staff_ids)))
        await session.execute(
            delete(staff_services).where(staff_services.c.staff_id.in_(staff_ids))
        )
        await session.execute(delete(Staff).where(Staff.id.in_(staff_ids)))

    if service_ids:
        await session.execute(
            delete(staff_services).where(staff_services.c.service_id.in_(service_ids))
        )
        await session.execute(delete(Service).where(Service.id.in_(service_ids)))

    if user_ids:
        await session.execute(
            delete(AuthSession).where(AuthSession.user_id.in_(user_ids))
        )
        await session.execute(
            delete(CustomerLedger).where(CustomerLedger.client_id.in_(user_ids))
        )
        await session.execute(
            delete(PromotionRedemption).where(
                PromotionRedemption.client_id.in_(user_ids)
            )
        )
        await session.execute(
            delete(CouponRedemption).where(
                CouponRedemption.redeemed_by_id.in_(user_ids)
            )
        )
        await session.execute(delete(User).where(User.id.in_(user_ids)))

    await session.execute(
        delete(StoreSchedule).where(StoreSchedule.store_id.in_(store_ids))
    )
    await session.execute(delete(Budget).where(Budget.store_id.in_(store_ids)))
    await session.execute(
        delete(PaymentGatewayConfig).where(PaymentGatewayConfig.store_id.in_(store_ids))
    )
    await session.execute(
        delete(StorePromotion).where(StorePromotion.store_id.in_(store_ids))
    )
    await session.execute(
        delete(StoreSubscription).where(StoreSubscription.store_id.in_(store_ids))
    )
    await session.execute(
        delete(WebhookInbox).where(WebhookInbox.store_id.in_(store_ids))
    )
    await session.execute(
        delete(OutboxMessage).where(OutboxMessage.store_id.in_(store_ids))
    )
    await session.execute(delete(Store).where(Store.id.in_(store_ids)))


def apply_attrs(instance: Any, **attrs: Any) -> None:
    for key, value in attrs.items():
        setattr(instance, key, value)


async def ensure_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    role: str,
    store_id: str,
    first_name: str,
    last_name: str,
    full_name: str | None = None,
    phone: str | None = None,
    is_global_admin: bool = False,
) -> User:
    user = await get_by(session, User, User.email == email)
    attrs = {
        "email": email,
        "hashed_password": hash_password(password),
        "full_name": full_name or f"{first_name} {last_name}".strip(),
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "role": role,
        "store_id": store_id,
        "is_global_admin": is_global_admin,
        "is_active": True,
    }
    if user is None:
        user = User(**attrs)
        session.add(user)
        await session.flush()
    else:
        apply_attrs(user, **attrs)
    return user


async def ensure_store(session: AsyncSession, scenario: dict[str, Any]) -> Store:
    store = await get_by(session, Store, Store.slug == scenario["slug"])
    attrs = {
        "name": scenario["name"],
        "slug": scenario["slug"],
        "primary_color": scenario["primary_color"],
        "requires_deposit": scenario["requires_deposit"],
        "deposit_percentage": scenario["deposit_percentage"],
        "cancellation_hours": scenario["cancellation_hours"],
        "min_booking_notice_hours": scenario["min_booking_notice_hours"],
        "buffer_minutes": scenario["buffer_minutes"],
        "send_email_confirmation": True,
        "send_email_reminders": True,
        "theme_config": scenario["theme_config"],
        "is_active": True,
    }
    if store is None:
        store = Store(**attrs)
        store.public_id = store.id
        session.add(store)
        await session.flush()
    else:
        apply_attrs(store, **attrs)
    return store


async def ensure_store_schedule(
    session: AsyncSession,
    store_id: str,
    day_of_week: int,
    open_time: time,
    close_time: time,
) -> StoreSchedule:
    schedule = await get_by(
        session,
        StoreSchedule,
        StoreSchedule.store_id == store_id,
        StoreSchedule.day_of_week == day_of_week,
    )
    attrs = {
        "store_id": store_id,
        "day_of_week": day_of_week,
        "open_time": open_time,
        "close_time": close_time,
        "is_active": True,
    }
    if schedule is None:
        schedule = StoreSchedule(**attrs)
        session.add(schedule)
        await session.flush()
    else:
        apply_attrs(schedule, **attrs)
    return schedule


async def ensure_service(
    session: AsyncSession, store_id: str, service_data: dict[str, Any]
) -> Service:
    service = await get_by(
        session,
        Service,
        Service.store_id == store_id,
        Service.name == service_data["name"],
    )
    attrs = {
        "store_id": store_id,
        "name": service_data["name"],
        "description": service_data["description"],
        "duration_minutes": service_data["duration"],
        "price": service_data["price"],
        "color": service_data["color"],
        "is_active": True,
    }
    if service is None:
        service = Service(**attrs)
        service.public_id = service.id
        session.add(service)
        await session.flush()
    else:
        apply_attrs(service, **attrs)
    return service


async def ensure_staff(
    session: AsyncSession,
    store_id: str,
    staff_data: dict[str, Any],
    service_ids: list[str],
) -> Staff:
    staff = await get_by(
        session,
        Staff,
        Staff.store_id == store_id,
        Staff.email == staff_data["email"],
    )
    attrs = {
        "first_name": staff_data["first_name"],
        "last_name": staff_data["last_name"],
        "display_name": staff_data["display_name"],
        "email": staff_data["email"],
        "store_id": store_id,
        "is_active": True,
    }
    if staff is None:
        staff = Staff(**attrs)
        session.add(staff)
        await session.flush()
    else:
        apply_attrs(staff, **attrs)
    return staff


async def ensure_staff_service_links(
    session: AsyncSession, staff_id: str, service_ids: list[str]
) -> None:
    desired = set(service_ids)
    existing_result = await session.execute(
        select(staff_services.c.service_id).where(staff_services.c.staff_id == staff_id)
    )
    existing = {row[0] for row in existing_result.fetchall()}

    for service_id in existing - desired:
        await session.execute(
            delete(staff_services).where(
                staff_services.c.staff_id == staff_id,
                staff_services.c.service_id == service_id,
            )
        )

    for service_id in desired - existing:
        await session.execute(
            insert(staff_services).values(
                staff_id=staff_id, service_id=service_id, rating=None
            )
        )


async def ensure_staff_schedule(
    session: AsyncSession,
    *,
    staff_id: str,
    store_id: str,
    day_of_week: int,
    start_hour: int,
    end_hour: int,
) -> Schedule:
    schedule = await get_by(
        session,
        Schedule,
        Schedule.staff_id == staff_id,
        Schedule.day_of_week == day_of_week,
    )
    attrs = {
        "staff_id": staff_id,
        "store_id": store_id,
        "day_of_week": day_of_week,
        "start_time": time(start_hour, 0),
        "end_time": time(end_hour, 0),
    }
    if schedule is None:
        schedule = Schedule(**attrs)
        session.add(schedule)
        await session.flush()
    else:
        apply_attrs(schedule, **attrs)
    return schedule


def make_dt(days_from_now: int, hour: int, minute: int = 0) -> datetime:
    base = NOW + timedelta(days=days_from_now)
    return base.replace(hour=hour, minute=minute)


async def ensure_appointment(
    session: AsyncSession,
    *,
    key: str,
    store_id: str,
    staff_id: str,
    service_id: str,
    client: User,
    starts_at: datetime,
    duration_minutes: int,
    status: str,
    notes: str,
    notes_staff: str | None = None,
) -> Appointment:
    appointment = await get_by(session, Appointment, Appointment.idempotency_key == key)
    ends_at = starts_at + timedelta(minutes=duration_minutes)
    attrs = {
        "store_id": store_id,
        "staff_id": staff_id,
        "service_id": service_id,
        "client_id": client.id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "duration_minutes": duration_minutes,
        "status": status,
        "notes": notes,
        "notes_staff": notes_staff,
        "cancelled_at": NOW if status == "cancelled" else None,
        "completed_at": NOW if status == "completed" else None,
        "idempotency_key": key,
    }
    if appointment is None:
        appointment = Appointment(**attrs)
        session.add(appointment)
        await session.flush()
    else:
        apply_attrs(appointment, **attrs)
    return appointment


async def ensure_block(
    session: AsyncSession,
    *,
    store_id: str,
    staff_id: str,
    start_time: datetime,
    end_time: datetime,
    reason: str,
) -> StaffBlock:
    block = await get_by(
        session,
        StaffBlock,
        StaffBlock.staff_id == staff_id,
        StaffBlock.start_time == start_time,
        StaffBlock.end_time == end_time,
    )
    attrs = {
        "store_id": store_id,
        "staff_id": staff_id,
        "start_time": start_time,
        "end_time": end_time,
        "reason": reason,
        "is_active": True,
    }
    if block is None:
        block = StaffBlock(**attrs)
        session.add(block)
        await session.flush()
    else:
        apply_attrs(block, **attrs)
    return block


async def ensure_budget(
    session: AsyncSession, store_id: str, budget_data: dict[str, Any]
) -> Budget:
    budget = await get_by(
        session,
        Budget,
        Budget.store_id == store_id,
        Budget.title == budget_data["title"],
    )
    attrs = {"store_id": store_id, **budget_data}
    if budget is None:
        budget = Budget(**attrs)
        session.add(budget)
        await session.flush()
    else:
        apply_attrs(budget, **attrs)
    return budget


async def ensure_audit_log(
    session: AsyncSession,
    *,
    actor: User | None,
    resource_type: str,
    resource_id: str,
    action: str,
    payload_before: dict[str, Any] | None,
    payload_after: dict[str, Any] | Sequence[Any] | None,
    context: str,
) -> AuditLog:
    log = await get_by(session, AuditLog, AuditLog.context == context)
    attrs = {
        "actor_id": actor.id if actor else None,
        "actor_public_id": actor.public_id if actor else None,
        "actor_email": actor.email if actor else None,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "action": action,
        "payload_before": payload_before,
        "payload_after": payload_after,
        "context": context,
    }
    if log is None:
        log = AuditLog(**attrs)
        session.add(log)
        await session.flush()
    else:
        apply_attrs(log, **attrs)
    return log


async def seed_store(session: AsyncSession, scenario: dict[str, Any]) -> dict[str, Any]:
    store = await ensure_store(session, scenario)
    for day_of_week, (open_time, close_time) in scenario["hours"].items():
        await ensure_store_schedule(
            session, store.id, day_of_week, open_time, close_time
        )

    admin_data = scenario["admin"]
    admin_user = await ensure_user(
        session,
        email=admin_data["email"],
        password=PASSWORDS["admin"],
        role=UserRole.ADMIN.value,
        store_id=store.id,
        first_name=admin_data["first_name"],
        last_name=admin_data["last_name"],
        full_name=admin_data["full_name"],
        phone=admin_data["phone"],
    )

    services_by_name = {}
    for service_data in scenario["services"]:
        service = await ensure_service(session, store.id, service_data)
        services_by_name[service.name] = service

    staff_records = []
    for staff_data in scenario["staff"]:
        await ensure_user(
            session,
            email=staff_data["email"],
            password=PASSWORDS["staff"],
            role=UserRole.STAFF.value,
            store_id=store.id,
            first_name=staff_data["first_name"],
            last_name=staff_data["last_name"],
            full_name=staff_data["display_name"],
            phone=staff_data["phone"],
        )
        service_ids = [
            services_by_name[name].id for name in staff_data["service_names"]
        ]
        staff = await ensure_staff(session, store.id, staff_data, service_ids)
        await ensure_staff_service_links(session, staff.id, service_ids)
        for day_of_week, (start_hour, end_hour) in staff_data["hours"].items():
            await ensure_staff_schedule(
                session,
                staff_id=staff.id,
                store_id=store.id,
                day_of_week=day_of_week,
                start_hour=start_hour,
                end_hour=end_hour,
            )
        for block_data in staff_data["blocks"]:
            start_time = make_dt(block_data["days_from_now"], block_data["start_hour"])
            end_time = start_time + timedelta(hours=block_data["duration_hours"])
            await ensure_block(
                session,
                store_id=store.id,
                staff_id=staff.id,
                start_time=start_time,
                end_time=end_time,
                reason=block_data["reason"],
            )
        staff_records.append(staff)

    client_records = []
    for client_data in scenario["clients"]:
        client = await ensure_user(
            session,
            email=client_data["email"],
            password=PASSWORDS["client"],
            role=UserRole.CLIENT.value,
            store_id=store.id,
            first_name=client_data["first_name"],
            last_name=client_data["last_name"],
            full_name=f"{client_data['first_name']} {client_data['last_name']}",
            phone=client_data["phone"],
        )
        client_records.append(client)

    appointment_statuses = [
        ("pending", 1),
        ("confirmed", 2),
        ("completed", -2),
        ("cancelled", -1),
        ("absent", -3),
    ]
    for index, (status, day_offset) in enumerate(appointment_statuses):
        staff = staff_records[index % len(staff_records)]
        service_name = scenario["staff"][index % len(scenario["staff"])][
            "service_names"
        ][0]
        service = services_by_name[service_name]
        client = client_records[index % len(client_records)]
        start_hour = 10 + (index * 2)
        notes_staff = None
        if status in {"confirmed", "completed"}:
            notes_staff = "Cliente frecuente. Confirmado manualmente."
        elif status == "absent":
            notes_staff = "No se presento al turno."
        await ensure_appointment(
            session,
            key=f"{SIMULATION_CONTEXT_PREFIX}:{scenario['slug']}:appointment:{index}",
            store_id=store.id,
            staff_id=staff.id,
            service_id=service.id,
            client=client,
            starts_at=make_dt(day_offset, start_hour),
            duration_minutes=service.duration_minutes,
            status=status,
            notes=f"Turno simulado para {scenario['name']}.",
            notes_staff=notes_staff,
        )

    for extra_index in range(3):
        staff = RNG.choice(staff_records)
        client = RNG.choice(client_records)
        service = services_by_name[RNG.choice(list(services_by_name.keys()))]
        await ensure_appointment(
            session,
            key=f"{SIMULATION_CONTEXT_PREFIX}:{scenario['slug']}:extra:{extra_index}",
            store_id=store.id,
            staff_id=staff.id,
            service_id=service.id,
            client=client,
            starts_at=make_dt(5 + extra_index, 11 + extra_index),
            duration_minutes=service.duration_minutes,
            status="confirmed" if extra_index % 2 == 0 else "pending",
            notes="Reserva adicional de simulacion.",
            notes_staff="Chequeado por el admin." if extra_index % 2 == 0 else None,
        )

    for budget_data in scenario["budgets"]:
        await ensure_budget(session, store.id, budget_data)

    await ensure_audit_log(
        session,
        actor=admin_user,
        resource_type="Store",
        resource_id=store.public_id,
        action=AuditAction.UPDATE.value,
        payload_before=None,
        payload_after={"slug": store.slug, "name": store.name},
        context=f"{SIMULATION_CONTEXT_PREFIX}:{scenario['slug']}:audit:store",
    )
    await ensure_audit_log(
        session,
        actor=admin_user,
        resource_type="Service",
        resource_id=next(iter(services_by_name.values())).public_id,
        action=AuditAction.CREATE.value,
        payload_before=None,
        payload_after={"count": len(services_by_name)},
        context=f"{SIMULATION_CONTEXT_PREFIX}:{scenario['slug']}:audit:services",
    )
    await ensure_audit_log(
        session,
        actor=admin_user,
        resource_type="Appointment",
        resource_id=f"{scenario['slug']}-batch",
        action=AuditAction.STATUS_CHANGE.value,
        payload_before={"status": "pending"},
        payload_after={"statuses_seeded": appointment_statuses},
        context=f"{SIMULATION_CONTEXT_PREFIX}:{scenario['slug']}:audit:appointments",
    )

    return {
        "store": store,
        "admin": admin_user,
        "services": len(services_by_name),
        "staff": len(staff_records),
        "clients": len(client_records),
    }


async def seed_global_admin(session: AsyncSession, default_store_id: str) -> User:
    return await ensure_user(
        session,
        email="global-admin@shifty.com",
        password=PASSWORDS["global_admin"],
        role=UserRole.ADMIN.value,
        store_id=default_store_id,
        first_name="Global",
        last_name="Admin",
        full_name="Global Admin",
        phone="+54 11 5000-0001",
        is_global_admin=True,
    )


async def summarize_counts(session: AsyncSession) -> dict[str, int]:
    models = [
        ("stores", Store),
        ("store_schedules", StoreSchedule),
        ("services", Service),
        ("staff", Staff),
        ("schedules", Schedule),
        ("appointments", Appointment),
        ("appointment_blocks", StaffBlock),
        ("budgets", Budget),
        ("audit_logs", AuditLog),
        ("users", User),
    ]
    summary = {}
    for label, model in models:
        result = await session.execute(select(model))
        summary[label] = len(result.scalars().all())

    result = await session.execute(select(staff_services.c.staff_id))
    summary["staff_services"] = len(result.fetchall())
    return summary


async def seed_simulation() -> None:
    print(f"[CONN] Seeding database at: {DATABASE_URL}")
    engine = create_async_engine(cast(str, DATABASE_URL), echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        await cleanup_seed(session)
        reports = []
        for scenario in STORE_SCENARIOS:
            report = await seed_store(session, scenario)
            reports.append(report)

        await seed_global_admin(session, reports[0]["store"].id)
        await session.commit()

        summary = await summarize_counts(session)
        print("[SUCCESS] Simulation data ready.")
        for report in reports:
            print(
                f"  - {report['store'].name}: "
                f"{report['services']} services, {report['staff']} staff, {report['clients']} clients"
            )
        print("[COUNTS]")
        for key in sorted(summary):
            print(f"  - {key}: {summary[key]}")
        print("[CREDENTIALS]")
        print("  - global-admin@shifty.com / global123")
        print("  - admin@barberia-sentinel.com / admin123")
        print("  - admin@salon-sentinel.com / admin123")
        print("  - Any staff email seeded / staff123")
        print("  - Any client email seeded / client123")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_simulation())
