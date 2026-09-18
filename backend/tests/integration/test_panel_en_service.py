"""El panel vive en un service + repository y devuelve los mismos numeros.

2026-09-18, hallazgo B5-08: toda la logica de ``/dashboard/summary`` (siete
consultas SQL, la regla "ingreso = pago acreditado", ocupacion, tendencia y el
armado de DTOs) vivia en el handler HTTP, una funcion de 160 lineas. CLAUDE.md
§2 pide router (HTTP) -> service (orquestacion) -> repository (consultas).

Dos pruebas: la estructural (el router no consulta la base, falla sobre el
codigo viejo) y la de caracterizacion, que fija cada numero del contrato de
respuesta con datos que ejercitan todas las ramas (cancelados fuera, pago no
acreditado fuera, semana pasada, cliente viejo fuera, orden de proximos). La de
caracterizacion pasa igual antes y despues del refactor: es la evidencia de que
mover el codigo no cambio los resultados.

Reloj congelado: "ahora" es el miercoles 2026-09-16 a las 15:00 ART (18:00Z).
"""

import ast
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import core.utils
from core.utils import local_to_utc
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import Payment, PaymentStatus
from modules.services.model import Service
from modules.staff.model import Schedule, Staff
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

HOY_LOCAL = date(2026, 9, 16)  # miercoles
AHORA = local_to_utc(HOY_LOCAL, time(15, 0))
BACKEND = Path(__file__).resolve().parents[2]


class _RelojCongelado(datetime):
    """``datetime`` cuyo ``now`` siempre devuelve AHORA; el resto es real."""

    @classmethod
    def now(cls, tz: object = None) -> "_RelojCongelado":
        fixed = AHORA if tz is None else AHORA.astimezone(cast(timezone, tz))
        return cls(
            fixed.year,
            fixed.month,
            fixed.day,
            fixed.hour,
            fixed.minute,
            fixed.second,
            fixed.microsecond,
            fixed.tzinfo,
        )


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_el_router_del_panel_no_consulta_la_base() -> None:
    router = BACKEND / "modules/dashboard/router.py"
    service = BACKEND / "modules/dashboard/service.py"
    repository = BACKEND / "modules/dashboard/repository.py"

    assert service.exists() and repository.exists()
    router_imports = _imports(router)
    assert not any(
        m.split(".", 1)[0] == "sqlalchemy"
        for m in router_imports - {"sqlalchemy.ext.asyncio"}
    ), sorted(router_imports)
    assert ".execute(" not in router.read_text(encoding="utf-8")
    # El service orquesta: ni HTTP ni SQL crudo; las consultas son del repo.
    service_imports = _imports(service)
    assert not any(m.split(".", 1)[0] == "fastapi" for m in service_imports)
    assert ".execute(" not in service.read_text(encoding="utf-8")


async def _turno(
    session: AsyncSession,
    *,
    store: Store,
    cliente: User,
    servicio: Service,
    staff: Staff,
    dia: date,
    hora: time,
    estado: AppointmentStatus,
    clave: str,
    pagos: tuple[tuple[Decimal, PaymentStatus], ...] = (),
) -> str:
    starts_at = local_to_utc(dia, hora)
    turno = Appointment(
        service_id=servicio.id,
        staff_id=staff.id,
        store_id=store.id,
        client_id=cliente.id,
        client_name="Cliente Panel",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=servicio.duration_minutes),
        duration_minutes=servicio.duration_minutes,
        price_amount=Decimal("10000.00"),
        status=estado.value,
        idempotency_key=f"b508-{clave}",
    )
    session.add(turno)
    await session.flush()
    for monto, estado_pago in pagos:
        session.add(
            Payment(
                store_id=store.id,
                appointment_id=turno.id,
                amount=monto,
                status=estado_pago.value,
                provider="manual",
            )
        )
    await session.commit()
    return turno.public_id


@pytest.mark.asyncio
async def test_el_panel_devuelve_los_mismos_numeros_y_contrato(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core.utils, "datetime", _RelojCongelado)

    store_public_id, token = await register_and_login(
        client, slug="b508-panel", email="b508@test.com"
    )
    corto_public_id = await create_service(client, token)  # 30 minutos
    staff_public_id = await create_staff(
        client, token, corto_public_id, email="pro-b508@test.com"
    )
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    corto = (
        await test_session.execute(
            select(Service).where(Service.public_id == corto_public_id)
        )
    ).scalar_one()
    staff = (
        await test_session.execute(select(Staff).where(Staff.id == staff_public_id))
    ).scalar_one()
    largo = Service(
        store_id=store.id, name="Largo", duration_minutes=60, price=Decimal("20000")
    )
    cliente_nuevo = User(
        email="nuevo-b508@test.com",
        hashed_password="no-se-loguea",
        first_name="Ana",
        last_name="Nueva",
        role=UserRole.CLIENT,
        store_id=store.id,
    )
    cliente_viejo = User(
        email="viejo-b508@test.com",
        hashed_password="no-se-loguea",
        first_name="Beto",
        last_name="Viejo",
        role=UserRole.CLIENT,
        store_id=store.id,
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    # Miercoles 09:00-17:00 = 480 minutos disponibles hoy.
    test_session.add_all([largo, cliente_nuevo, cliente_viejo])
    test_session.add(
        Schedule(
            staff_id=staff.id,
            store_id=store.id,
            day_of_week=HOY_LOCAL.weekday(),
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
    )
    await test_session.commit()

    async def turno(
        clave: str,
        dia: date,
        hora: time,
        servicio: Service,
        estado: AppointmentStatus,
        pagos: tuple[tuple[Decimal, PaymentStatus], ...] = (),
    ) -> str:
        return await _turno(
            test_session,
            store=store,
            cliente=cliente_nuevo,
            servicio=servicio,
            staff=staff,
            dia=dia,
            hora=hora,
            estado=estado,
            clave=clave,
            pagos=pagos,
        )

    acreditado = PaymentStatus.MANUAL_CONFIRMED
    hoy_pendiente = await turno(
        "hoy-16", HOY_LOCAL, time(16, 0), corto, AppointmentStatus.PENDING
    )
    hoy_confirmado = await turno(
        "hoy-17",
        HOY_LOCAL,
        time(17, 0),
        largo,
        AppointmentStatus.CONFIRMED,
        ((Decimal("8000.00"), acreditado),),
    )
    # Cancelado hoy: fuera de "hoy", de minutos reservados y del promedio.
    await turno("hoy-10", HOY_LOCAL, time(10, 0), largo, AppointmentStatus.CANCELLED)
    # Lunes y martes de esta semana, ya pasados: el pago aprobado cuenta como
    # ingreso, el pendiente no.
    await turno(
        "lunes",
        date(2026, 9, 14),
        time(10, 0),
        corto,
        AppointmentStatus.COMPLETED,
        ((Decimal("2000.00"), PaymentStatus.APPROVED),),
    )
    await turno(
        "martes",
        date(2026, 9, 15),
        time(10, 0),
        corto,
        AppointmentStatus.COMPLETED,
        ((Decimal("999.00"), PaymentStatus.PENDING),),
    )
    domingo = await turno(
        "domingo", date(2026, 9, 20), time(11, 0), largo, AppointmentStatus.PENDING
    )
    # Semana pasada: solo alimenta la tendencia.
    await turno(
        "semana-pasada",
        date(2026, 9, 9),
        time(10, 0),
        corto,
        AppointmentStatus.COMPLETED,
        ((Decimal("4000.00"), acreditado),),
    )

    res = await client.get("/dashboard/summary", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    cuerpo = res.json()

    assert set(cuerpo) == {"stats", "upcoming_appointments"}
    assert cuerpo["stats"] == {
        "appointments_today": 2,
        "pending_confirmations": 2,
        # (30 + 60) reservados sobre 480 disponibles.
        "occupancy_rate": 18.75,
        "new_clients_last_30d": 1,
        # 8000 acreditado + 2000 aprobado; el pendiente de 999 no es ingreso.
        "weekly_revenue": 10000.0,
        # (10000 - 4000) / 4000.
        "revenue_trend": 150.0,
        # Semana sin cancelados: 30, 60, 30, 30, 60.
        "average_appointment_minutes": 42,
    }
    proximos = cuerpo["upcoming_appointments"]
    assert [p["public_id"] for p in proximos] == [
        hoy_pendiente,
        hoy_confirmado,
        domingo,
    ]
    assert set(proximos[0]) == {
        "public_id",
        "starts_at",
        "status",
        "service_name",
        "staff_name",
        "client_name",
    }
    assert [
        (p["status"], p["service_name"], p["staff_name"], p["client_name"])
        for p in proximos
    ] == [
        ("pending", "Consulta", "Pro Demo", "Ana Nueva"),
        ("confirmed", "Largo", "Pro Demo", "Ana Nueva"),
        ("pending", "Largo", "Pro Demo", "Ana Nueva"),
    ]
