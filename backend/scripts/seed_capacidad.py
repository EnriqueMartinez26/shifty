"""Seed de capacidad para la prueba de aceptacion (plan §9, plan-capacidad §5.3).

SOLO PARA STAGING. Siembra ``--stores`` tiendas (200 por defecto) con slug
``cap-NNN``, cada una con:

- suscripcion activa (plan "Capacidad (prueba)"), flags por defecto (sin
  pagos ni OTP), horario de lunes a sabado de 09 a 19;
- 3-6 servicios, 2-4 profesionales con horario semanal y todos los servicios;
- un dueno ``owner-NNN@<dominio>`` con la contrasena de ``SEED_OWNER_PASSWORD``
  (nunca se imprime ni tiene valor por defecto);
- 30 clientes con email tecnico ``.noreply`` (nunca reciben correo);
- 90 dias de historial (~6 turnos por dia habil: completados, cancelados y
  ausentes), los proximos 14 dias ocupados al 40 % y dos bloqueos.

Se niega si ``ENV`` o la configuracion cargada dicen produccion (regla 17:
falla cerrado). Es idempotente por slug: una tienda ``cap-NNN`` que ya existe
no se toca y solo entra al manifiesto. Cada tienda va en su propia
transaccion, asi que un corte deja tiendas enteras o nada.

Corre dentro del contenedor del backend, con el rol de la app y el bypass
explicito de RLS (``set_tenant_context(None, True)``), como
``seed_simulation.py`` y los jobs de Celery. Al final escribe un manifiesto
JSON (ids publicos y emails de los duenos, sin contrasenas) para Locust:

    ENV=staging SEED_OWNER_PASSWORD=... python scripts/seed_capacidad.py \\
        --stores 5 --manifest /tmp/capacidad.json     # validar primero con 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import ulid  # noqa: E402
from sqlalchemy import insert, select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import Environment, redact_url, settings  # noqa: E402
from core.database import (  # noqa: E402
    TenantSession,
    _apply_tenant_context,
    set_tenant_context,
)
from core.model_registry import load_all_models  # noqa: E402
from core.security import hash_password  # noqa: E402
from core.utils import local_to_utc, today_local  # noqa: E402
from modules.appointments.model import Appointment  # noqa: E402
from modules.billing.model import Plan, StoreSubscription  # noqa: E402
from modules.services.model import Service  # noqa: E402
from modules.staff.model import Schedule, Staff, StaffBlock, staff_services  # noqa: E402
from modules.stores.model import Store, StoreSchedule  # noqa: E402
from modules.users.model import User, UserRole  # noqa: E402

SLUG_PREFIX = "cap-"
PLAN_NAME = "Capacidad (prueba)"
DEFAULT_DOMAIN = "capacidad.example.com"
MIN_PASSWORD_LENGTH = 12
ENTORNOS_PERMITIDOS = {Environment.STAGING.value, Environment.DEVELOPMENT.value}
APERTURA, CIERRE = 9, 19
DIAS_HABILES = range(0, 6)  # lunes a sabado
CLIENTES_POR_TIENDA = 30
SERVICIOS = (
    ("Corte", 30, 8000),
    ("Color", 60, 25000),
    ("Barba", 30, 6000),
    ("Tratamiento", 45, 15000),
    ("Peinado", 45, 12000),
    ("Consulta", 30, 5000),
)


def verificar_entorno(environ: Mapping[str, str]) -> str:
    """Contrasena de los duenos si el entorno es staging o desarrollo.

    Se niega con produccion en la variable O en la configuracion cargada, y
    con cualquier otro valor: sembrar cuentas con clave conocida exige decir
    explicitamente donde.
    """
    env = environ.get("ENV", "").strip().lower()
    cargado = str(getattr(settings.ENV, "value", settings.ENV)).lower()
    if Environment.PRODUCTION.value in (env, cargado):
        raise SystemExit(
            "seed_capacidad se niega en produccion: crea cuentas con una "
            "contrasena conocida. Correrlo solo en staging."
        )
    if env not in ENTORNOS_PERMITIDOS:
        raise SystemExit(
            f"ENV tiene que ser staging o development (es {env or 'vacio'!r})"
        )
    password = environ.get("SEED_OWNER_PASSWORD", "")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(
            "Falta SEED_OWNER_PASSWORD (minimo "
            f"{MIN_PASSWORD_LENGTH} caracteres): es la clave de los duenos."
        )
    return password


def slug_de(indice: int) -> str:
    return f"{SLUG_PREFIX}{indice:03d}"


@dataclass(frozen=True)
class TurnoPlaneado:
    profesional: int
    servicio: int
    cliente: int
    dia: date
    hora: int
    minutos: int
    estado: str


def planear_turnos(
    rng: random.Random,
    *,
    hoy: date,
    profesionales: int,
    duraciones: Sequence[int],
    clientes: int,
    dias_historial: int,
    por_dia: int,
    dias_futuros: int,
    ocupacion: float,
) -> list[TurnoPlaneado]:
    """Turnos en una grilla de una hora por profesional: nunca se superponen.

    Las duraciones son de hasta 60 minutos, asi que un turno por hora y
    profesional respeta la exclusion GiST. Pasado: terminados; futuro:
    pendientes o confirmados (los que el trigger acepta al insertar).
    """
    horas = list(range(APERTURA, CIERRE))
    grilla = [(p, h) for p in range(profesionales) for h in horas]
    plan: list[TurnoPlaneado] = []

    def turno(dia: date, profesional: int, hora: int, estado: str) -> TurnoPlaneado:
        servicio = rng.randrange(len(duraciones))
        return TurnoPlaneado(
            profesional=profesional,
            servicio=servicio,
            cliente=rng.randrange(clientes),
            dia=dia,
            hora=hora,
            minutos=duraciones[servicio],
            estado=estado,
        )

    for atras in range(1, dias_historial + 1):
        dia = hoy - timedelta(days=atras)
        if dia.weekday() not in DIAS_HABILES:
            continue
        for profesional, hora in rng.sample(grilla, k=min(por_dia, len(grilla))):
            estado = rng.choices(
                ("completed", "cancelled", "absent"), weights=(80, 12, 8)
            )[0]
            plan.append(turno(dia, profesional, hora, estado))

    por_profesional = round(len(horas) * ocupacion)
    for adelante in range(1, dias_futuros + 1):
        dia = hoy + timedelta(days=adelante)
        if dia.weekday() not in DIAS_HABILES:
            continue
        for profesional in range(profesionales):
            for hora in rng.sample(horas, k=por_profesional):
                estado = rng.choice(("pending", "confirmed"))
                plan.append(turno(dia, profesional, hora, estado))
    return plan


@dataclass(frozen=True)
class Opciones:
    stores: int
    dias_historial: int
    por_dia: int
    dias_futuros: int
    ocupacion: float
    dominio: str
    manifiesto: Path


async def _plan_de_prueba(session: AsyncSession) -> Plan:
    plan = (
        await session.execute(select(Plan).where(Plan.name == PLAN_NAME))
    ).scalar_one_or_none()
    if plan is None:
        plan = Plan(
            name=PLAN_NAME,
            description="Plan de la prueba de capacidad (staging)",
            price=Decimal(0),
        )
        session.add(plan)
        await session.flush()
    return plan


async def _entrada_existente(session: AsyncSession, store: Store) -> dict[str, Any]:
    servicios = (
        await session.execute(
            select(Service.public_id).where(Service.store_id == store.id)
        )
    ).scalars()
    profesionales = (
        await session.execute(select(Staff.id).where(Staff.store_id == store.id))
    ).scalars()
    dueno = (
        await session.execute(
            select(User.email).where(
                User.store_id == store.id, User.role == UserRole.ADMIN.value
            )
        )
    ).scalars()
    return {
        "slug": store.slug,
        "store_public_id": str(store.public_id),
        "owner_email": next(iter(dueno), ""),
        "service_ids": [str(s) for s in servicios],
        "staff_ids": [str(p) for p in profesionales],
    }


async def _tienda(session: AsyncSession, indice: int, plan: Plan) -> Store:
    """Tienda, horario de lunes a sabado y suscripcion activa."""
    # id y public_id iguales, como el alta desde el superadmin: el
    # store_public_id externo coincide con el store_id de RLS.
    store_id = str(ulid.ULID())
    store = Store(
        id=store_id,
        public_id=store_id,
        name=f"Capacidad {indice:03d}",
        slug=slug_de(indice),
        theme_config={"business_type": "general"},
        is_active=True,
    )
    session.add(store)
    await session.flush()
    for dow in DIAS_HABILES:
        session.add(
            StoreSchedule(
                store_id=store_id,
                day_of_week=dow,
                open_time=time(APERTURA),
                close_time=time(CIERRE),
            )
        )
    ahora = datetime.now(timezone.utc)
    session.add(
        StoreSubscription(
            store_id=store_id,
            plan_id=plan.id,
            plan_name=PLAN_NAME,
            status="active",
            base_amount=Decimal(0),
            total_amount=Decimal(0),
            current_period_start=ahora - timedelta(days=1),
            current_period_end=ahora + timedelta(days=365),
        )
    )
    return store


async def _catalogo_y_personal(
    session: AsyncSession,
    rng: random.Random,
    *,
    store_id: str,
    indice: int,
    dominio: str,
) -> tuple[list[Service], list[Staff]]:
    """3-6 servicios y 2-4 profesionales que hacen todos, con horario."""
    servicios = [
        Service(
            store_id=store_id,
            name=nombre,
            description="Servicio de la prueba de capacidad",
            duration_minutes=minutos,
            price=Decimal(precio),
            is_active=True,
        )
        for nombre, minutos, precio in rng.sample(SERVICIOS, k=rng.randint(3, 6))
    ]
    profesionales = [
        Staff(
            store_id=store_id,
            first_name=f"Pro{n}",
            last_name=f"{indice:03d}",
            display_name=f"Pro {n}",
            email=f"pro{n}-{indice:03d}@{dominio}",
            is_active=True,
        )
        for n in range(rng.randint(2, 4))
    ]
    session.add_all([*servicios, *profesionales])
    await session.flush()
    for profesional in profesionales:
        await session.execute(
            insert(staff_services),
            [{"staff_id": profesional.id, "service_id": s.id} for s in servicios],
        )
        session.add_all(
            Schedule(
                staff_id=profesional.id,
                store_id=store_id,
                day_of_week=dow,
                start_time=time(APERTURA),
                end_time=time(CIERRE),
            )
            for dow in DIAS_HABILES
        )
    return servicios, profesionales


def _personas(
    *, store_id: str, indice: int, owner_email: str, hash_dueno: str
) -> tuple[User, list[User]]:
    """El dueno y 30 clientes con email tecnico (nunca reciben correo)."""
    dueno = User(
        email=owner_email,
        hashed_password=hash_dueno,
        first_name="Dueno",
        last_name=f"{indice:03d}",
        full_name=f"Dueno {indice:03d}",
        role=UserRole.ADMIN,
        store_id=store_id,
    )
    clientes = []
    for n in range(CLIENTES_POR_TIENDA):
        telefono = f"+549115{indice:03d}{n:04d}"
        clientes.append(
            User(
                email=f"{telefono}@store{store_id}.noreply".lower(),
                hashed_password=hash_dueno,
                first_name="Cliente",
                last_name=f"{n:04d}",
                full_name=f"Cliente {n:04d}",
                phone=telefono,
                role=UserRole.CLIENT,
                store_id=store_id,
            )
        )
    return dueno, clientes


def _turno(
    t: TurnoPlaneado,
    *,
    clave: str,
    store_id: str,
    servicios: list[Service],
    profesionales: list[Staff],
    clientes: list[User],
) -> Appointment:
    inicio = local_to_utc(t.dia, time(t.hora))
    fin = inicio + timedelta(minutes=t.minutos)
    cliente = clientes[t.cliente]
    servicio = servicios[t.servicio]
    return Appointment(
        store_id=store_id,
        staff_id=profesionales[t.profesional].id,
        service_id=servicio.id,
        client_id=cliente.id,
        client_name=cliente.full_name,
        client_email=cliente.email,
        client_phone=cliente.phone,
        starts_at=inicio,
        ends_at=fin,
        duration_minutes=t.minutos,
        price_amount=servicio.price,
        status=t.estado,
        completed_at=fin if t.estado == "completed" else None,
        cancelled_at=inicio - timedelta(hours=2) if t.estado == "cancelled" else None,
        idempotency_key=clave,
    )


async def _sembrar_tienda(
    session: AsyncSession,
    indice: int,
    *,
    opciones: Opciones,
    hash_dueno: str,
    plan: Plan,
    hoy: date,
) -> dict[str, Any]:
    rng = random.Random(indice)
    store = await _tienda(session, indice, plan)
    store_id = str(store.id)
    servicios, profesionales = await _catalogo_y_personal(
        session, rng, store_id=store_id, indice=indice, dominio=opciones.dominio
    )
    owner_email = f"owner-{indice:03d}@{opciones.dominio}"
    dueno, clientes = _personas(
        store_id=store_id,
        indice=indice,
        owner_email=owner_email,
        hash_dueno=hash_dueno,
    )
    session.add_all([dueno, *clientes])
    await session.flush()

    plan_turnos = planear_turnos(
        rng,
        hoy=hoy,
        profesionales=len(profesionales),
        duraciones=[s.duration_minutes for s in servicios],
        clientes=len(clientes),
        dias_historial=opciones.dias_historial,
        por_dia=opciones.por_dia,
        dias_futuros=opciones.dias_futuros,
        ocupacion=opciones.ocupacion,
    )
    session.add_all(
        _turno(
            t,
            clave=f"{store.slug}:{n}",
            store_id=store_id,
            servicios=servicios,
            profesionales=profesionales,
            clientes=clientes,
        )
        for n, t in enumerate(plan_turnos)
    )
    for dias in (20, 35):
        inicio = local_to_utc(hoy + timedelta(days=dias), time(13))
        session.add(
            StaffBlock(
                store_id=store_id,
                staff_id=rng.choice(profesionales).id,
                start_time=inicio,
                end_time=inicio + timedelta(hours=1),
                reason="Tramite",
                is_active=True,
            )
        )
    await session.flush()
    return {
        "slug": store.slug,
        "store_public_id": str(store.public_id),
        "owner_email": owner_email,
        "service_ids": [str(s.public_id) for s in servicios],
        "staff_ids": [str(p.public_id) for p in profesionales],
    }


async def sembrar(database_url: str, opciones: Opciones, password: str) -> int:
    load_all_models()
    engine = create_async_engine(database_url, pool_size=2, max_overflow=0)
    sesiones = async_sessionmaker(engine, class_=TenantSession, expire_on_commit=False)
    # Una sola vez: bcrypt de 12 rondas por dueno serian minutos de CPU.
    hash_dueno = hash_password(password)
    hoy = today_local()
    entradas: list[dict[str, Any]] = []
    creadas = 0
    # Bypass explicito de RLS, como los jobs de Celery y seed_simulation.
    set_tenant_context(None, True)
    try:
        for indice in range(1, opciones.stores + 1):
            async with sesiones() as session:
                await _apply_tenant_context(session)
                existente = (
                    await session.execute(
                        select(Store).where(Store.slug == slug_de(indice))
                    )
                ).scalar_one_or_none()
                if existente is not None:
                    entradas.append(await _entrada_existente(session, existente))
                    continue
                plan = await _plan_de_prueba(session)
                entradas.append(
                    await _sembrar_tienda(
                        session,
                        indice,
                        opciones=opciones,
                        hash_dueno=hash_dueno,
                        plan=plan,
                        hoy=hoy,
                    )
                )
                await session.commit()
                creadas += 1
            if indice % 10 == 0:
                print(f"[seed] {indice}/{opciones.stores} tiendas")
    finally:
        set_tenant_context(None, False)
        await engine.dispose()

    opciones.manifiesto.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "stores": entradas,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"[seed] {creadas} tiendas nuevas, {len(entradas) - creadas} ya existian; "
        f"manifiesto: {opciones.manifiesto} (sin contrasenas)"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed de capacidad (SOLO staging): tiendas cap-NNN con historial."
    )
    parser.add_argument("--stores", type=int, default=200)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--per-day", type=int, default=6)
    parser.add_argument("--future-days", type=int, default=14)
    parser.add_argument("--occupancy", type=float, default=0.4)
    parser.add_argument("--domain", default=DEFAULT_DOMAIN)
    parser.add_argument("--manifest", default="capacidad-manifiesto.json")
    args = parser.parse_args(argv)

    # Primero la guarda: nada se conecta si el entorno no es el correcto.
    password = verificar_entorno(os.environ)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise SystemExit("Falta DATABASE_URL (el rol de la app, dentro del backend)")
    opciones = Opciones(
        stores=max(1, min(args.stores, 999)),
        dias_historial=max(0, min(args.days, 365)),
        por_dia=max(0, min(args.per_day, 30)),
        dias_futuros=max(0, min(args.future_days, 60)),
        ocupacion=max(0.0, min(args.occupancy, 1.0)),
        dominio=args.domain,
        manifiesto=Path(args.manifest),
    )
    print(f"[seed] base: {redact_url(database_url, keep_target=True)}")
    return asyncio.run(sembrar(database_url, opciones, password))


if __name__ == "__main__":
    raise SystemExit(main())
