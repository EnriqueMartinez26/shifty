"""Reportes, panel y SLO sin funciones de mas de 80 lineas, con los mismos numeros.

2026-09-18, hallazgo B5-09 (regla 29): ``_aggregate_summary`` (123 lineas,
cuatro responsabilidades: cohortes, conteo por estado, nombres e items),
``get_professionals`` (150), ``get_summary`` (100), ``slo_status`` (85) y el
handler del panel (160, resuelto en B5-08) pasaban el tope. Las cohortes
(``new_clients``, ``inactive_clients``) y el reporte por profesional no tenian
un test que fijara sus numeros, asi que partir esas funciones no tenia red.

La prueba estructural falla sobre el codigo viejo. Las de caracterizacion
fijan cada numero del contrato (resumen, cohortes, items, profesionales con
horario y bloqueos recortados al rango, SLO con alertas) y pasan igual antes y
despues de la extraccion: es la evidencia de que no cambio ningun resultado.
"""

import ast
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.utils import local_to_utc
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.model import OutboxMessage, Payment, PaymentStatus, WebhookInbox
from modules.services.model import Service
from modules.staff.model import Schedule, Staff, StaffBlock
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

BACKEND = Path(__file__).resolve().parents[2]
MAX_LINEAS = 80
ARCHIVOS_DEL_LOTE = (
    "modules/reports/service.py",
    "modules/reports/router.py",
    "modules/reports/exporter.py",
    "modules/dashboard/router.py",
    "modules/dashboard/service.py",
    "modules/dashboard/repository.py",
    "modules/ops/router.py",
    "modules/audit/repository.py",
)


def test_ninguna_funcion_del_lote_pasa_las_80_lineas() -> None:
    largas: list[str] = []
    for relativo in ARCHIVOS_DEL_LOTE:
        ruta = BACKEND / relativo
        arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert nodo.end_lineno is not None
                lineas = nodo.end_lineno - nodo.lineno + 1
                if lineas > MAX_LINEAS:
                    largas.append(f"{relativo}:{nodo.lineno} {nodo.name} ({lineas})")
    assert largas == []


class _Semilla:
    def __init__(
        self,
        session: AsyncSession,
        store: Store,
        staff: Staff,
    ) -> None:
        self.session = session
        self.store = store
        self.staff = staff

    def cliente(self, nombre: str, apellido: str) -> User:
        cliente = User(
            email=f"{nombre.lower()}-b509@test.com",
            hashed_password="no-se-loguea",
            first_name=nombre,
            last_name=apellido,
            role=UserRole.CLIENT,
            store_id=self.store.id,
        )
        self.session.add(cliente)
        return cliente

    async def turno(
        self,
        clave: str,
        dia: date,
        hora: time,
        servicio: Service,
        cliente: User,
        estado: AppointmentStatus,
        *,
        precio: Decimal | None,
        pago: tuple[Decimal, PaymentStatus] | None = None,
    ) -> str:
        starts_at = local_to_utc(dia, hora)
        turno = Appointment(
            service_id=servicio.id,
            staff_id=self.staff.id,
            store_id=self.store.id,
            client_id=cliente.id,
            client_name="Snapshot",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=servicio.duration_minutes),
            duration_minutes=servicio.duration_minutes,
            price_amount=precio,
            status=estado.value,
            idempotency_key=f"b509-{clave}",
        )
        self.session.add(turno)
        await self.session.flush()
        if pago is not None:
            self.session.add(
                Payment(
                    store_id=self.store.id,
                    appointment_id=turno.id,
                    amount=pago[0],
                    status=pago[1].value,
                    provider="manual",
                )
            )
        await self.session.commit()
        return turno.public_id


async def _tienda(
    client: AsyncClient, test_session: AsyncSession, slug: str
) -> tuple[str, Store, Staff, Service]:
    store_public_id, token = await register_and_login(
        client, slug=slug, email=f"{slug}@test.com"
    )
    corto_public_id = await create_service(client, token)  # 30 min, 10000
    staff_public_id = await create_staff(
        client, token, corto_public_id, email=f"pro-{slug}@test.com"
    )
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    staff = (
        await test_session.execute(select(Staff).where(Staff.id == staff_public_id))
    ).scalar_one()
    corto = (
        await test_session.execute(
            select(Service).where(Service.public_id == corto_public_id)
        )
    ).scalar_one()
    return token, store, staff, corto


@pytest.mark.asyncio
async def test_resumen_cohortes_y_profesionales_no_cambian(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, store, staff, corto = await _tienda(client, test_session, "b509-rep")
    largo = Service(
        store_id=store.id, name="Largo", duration_minutes=60, price=Decimal("20000")
    )
    zoe = Staff(store_id=store.id, first_name="Zoe", last_name="Z", display_name="Zoe")
    baja = Staff(
        store_id=store.id,
        first_name="Baja",
        last_name="B",
        display_name="Baja",
        is_active=False,
    )
    test_session.add_all([largo, zoe, baja])
    semilla = _Semilla(test_session, store, staff)
    ana = semilla.cliente("Ana", "Alvarez")
    beto = semilla.cliente("Beto", "Blanco")
    carla = semilla.cliente("Carla", "Castro")
    # Lunes 09-13 (1 lunes en el rango) + miercoles 10-12 (2) = 480 minutos.
    test_session.add_all(
        [
            Schedule(
                staff_id=staff.id,
                store_id=store.id,
                day_of_week=0,
                start_time=time(9, 0),
                end_time=time(13, 0),
            ),
            Schedule(
                staff_id=staff.id,
                store_id=store.id,
                day_of_week=2,
                start_time=time(10, 0),
                end_time=time(12, 0),
            ),
            # Bloqueo adentro del rango (60) y otro que empieza antes y se
            # recorta al inicio del rango (60 de 120).
            StaffBlock(
                staff_id=staff.id,
                store_id=store.id,
                start_time=local_to_utc(date(2026, 9, 7), time(10, 0)),
                end_time=local_to_utc(date(2026, 9, 7), time(11, 0)),
                reason="Tramite",
            ),
            StaffBlock(
                staff_id=staff.id,
                store_id=store.id,
                start_time=local_to_utc(date(2026, 8, 31), time(23, 0)),
                end_time=local_to_utc(date(2026, 9, 1), time(1, 0)),
                reason="Guardia",
            ),
        ]
    )
    await test_session.commit()

    acreditado = PaymentStatus.MANUAL_CONFIRMED
    # Antes del rango: Ana vuelve (returning), Carla no vuelve (inactive).
    await semilla.turno(
        "ana-ago", date(2026, 8, 20), time(10, 0), corto, ana,
        AppointmentStatus.COMPLETED, precio=Decimal("10000"),
    )  # fmt: skip
    await semilla.turno(
        "carla-ago", date(2026, 8, 15), time(10, 0), corto, carla,
        AppointmentStatus.COMPLETED, precio=Decimal("10000"),
    )  # fmt: skip
    t1 = await semilla.turno(
        "t1", date(2026, 9, 2), time(10, 0), corto, ana,
        AppointmentStatus.COMPLETED, precio=Decimal("9000"),
        pago=(Decimal("10000.00"), acreditado),
    )  # fmt: skip
    t2 = await semilla.turno(
        "t2", date(2026, 9, 3), time(10, 30), largo, beto,
        AppointmentStatus.CONFIRMED, precio=Decimal("20000"),
        pago=(Decimal("5000.00"), PaymentStatus.APPROVED),
    )  # fmt: skip
    t3 = await semilla.turno(
        "t3", date(2026, 9, 7), time(9, 0), corto, beto,
        AppointmentStatus.CANCELLED, precio=Decimal("10000"),
    )  # fmt: skip
    t4 = await semilla.turno(
        "t4", date(2026, 9, 9), time(11, 0), corto, ana,
        AppointmentStatus.ABSENT, precio=Decimal("10000"),
    )  # fmt: skip
    # 22:30 ART del dia 10 = 01:30Z del 11: sigue siendo del rango.
    t5 = await semilla.turno(
        "t5", date(2026, 9, 10), time(22, 30), largo, ana,
        AppointmentStatus.PENDING, precio=None,
    )  # fmt: skip
    t6 = await semilla.turno(
        "t6", date(2026, 9, 9), time(10, 0), corto, beto,
        AppointmentStatus.PENDING_PAYMENT, precio=Decimal("10000"),
    )  # fmt: skip
    t7 = await semilla.turno(
        "t7", date(2026, 9, 8), time(10, 0), corto, beto,
        AppointmentStatus.EXPIRED, precio=Decimal("10000"),
    )  # fmt: skip

    rango = {"from_date": "2026-09-01", "to_date": "2026-09-10"}
    res = await client.get(
        "/reports/summary", params=rango, headers=auth_headers(token)
    )
    assert res.status_code == 200, res.text
    resumen = res.json()
    assert resumen["stats"] == {
        "total_appointments": 7,
        "completed_appointments": 1,
        "cancelled_appointments": 1,
        "pending_appointments": 2,
        "confirmed_appointments": 1,
        "total_revenue": 15000.0,
        "average_ticket": 2142.86,
        # B5-10 (aditivo): el cancelado t3 no tiene pago, no hay sena retenida.
        "retained_deposit_revenue": 0.0,
    }
    assert resumen["client_stats"] == {
        "total_clients": 2,
        "new_clients": 1,
        "returning_clients": 1,
        "inactive_clients": 1,
    }
    assert [
        (
            s["service_name"],
            s["appointments"],
            s["completed_appointments"],
            s["revenue"],
        )
        for s in resumen["top_services"]
    ] == [("Consulta", 3, 1, 10000.0), ("Largo", 2, 0, 5000.0)]
    assert [
        (c["client_name"], c["appointments"], c["completed_appointments"], c["revenue"])
        for c in resumen["top_clients"]
    ] == [("Ana Alvarez", 3, 1, 10000.0), ("Beto Blanco", 2, 0, 5000.0)]
    assert resumen["debt_summary"] == {
        "outstanding_balance": 0.0,
        "debtors_count": 0,
        "average_debt": 0.0,
        "top_debtors": [],
    }
    items: list[dict[str, Any]] = resumen["appointments"]
    assert [
        (i["public_id"], i["status"], i["client_name"], i["service_price"])
        for i in items
    ] == [
        (t1, "completed", "Ana Alvarez", 9000.0),
        (t2, "confirmed", "Beto Blanco", 20000.0),
        (t3, "cancelled", "Beto Blanco", 10000.0),
        (t7, "expired", "Beto Blanco", 10000.0),
        (t6, "pending_payment", "Beto Blanco", 10000.0),
        (t4, "absent", "Ana Alvarez", 10000.0),
        # Sin snapshot de precio: cae al precio de lista del servicio.
        (t5, "pending", "Ana Alvarez", 20000.0),
    ]
    assert {i["staff_name"] for i in items} == {"Pro Demo"}

    res = await client.get(
        "/reports/professionals", params=rango, headers=auth_headers(token)
    )
    assert res.status_code == 200, res.text
    profesionales = res.json()
    assert (profesionales["from_date"], profesionales["to_date"]) == (
        "2026-09-01",
        "2026-09-10",
    )
    assert profesionales["professionals"] == [
        {
            "staff_id": staff.id,
            "staff_name": "Pro Demo",
            "appointments": 7,
            "completed_appointments": 1,
            "confirmed_appointments": 1,
            "absent_appointments": 1,
            "cancelled_appointments": 1,
            # 30 + 60 + 30 + 60 + 30: sin el cancelado ni el vencido.
            "used_minutes": 210,
            "used_hours": 3.5,
            "available_minutes": 480,
            "available_hours": 8.0,
            "blocked_minutes": 120,
            "blocked_hours": 2.0,
            # 210 / (480 - 120).
            "occupancy_rate": 58.33,
            "revenue": 15000.0,
        },
        {
            "staff_id": zoe.id,
            "staff_name": "Zoe",
            "appointments": 0,
            "completed_appointments": 0,
            "confirmed_appointments": 0,
            "absent_appointments": 0,
            "cancelled_appointments": 0,
            "used_minutes": 0,
            "used_hours": 0.0,
            "available_minutes": 0,
            "available_hours": 0.0,
            "blocked_minutes": 0,
            "blocked_hours": 0.0,
            "occupancy_rate": 0.0,
            "revenue": 0.0,
        },
    ]


@pytest.mark.asyncio
async def test_slo_no_cambia(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "SLO_MAX_PENDING_WEBHOOKS", 2)
    monkeypatch.setattr(settings, "SLO_MAX_FAILED_WEBHOOKS", 5)
    monkeypatch.setattr(settings, "SLO_MAX_PENDING_OUTBOX", 1)
    token, store, _, _ = await _tienda(client, test_session, "b509-slo")
    procesado = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def webhook(clave: str, **extra: Any) -> WebhookInbox:
        datos: dict[str, Any] = {"store_id": store.id, "payload": {}}
        datos.update(extra)
        return WebhookInbox(event_id=f"b509-{clave}", **datos)

    def outbox(**extra: Any) -> OutboxMessage:
        datos: dict[str, Any] = {
            "store_id": store.id,
            "event_type": "b509",
            "payload": {},
        }
        datos.update(extra)
        return OutboxMessage(**datos)

    test_session.add_all(
        [
            webhook("p1"),
            webhook("p2"),
            webhook("p3", error="boom"),
            webhook("ok", processed_at=procesado),
            webhook("inactivo", is_active=False),
            webhook("ajeno", store_id="otra-tienda"),
            outbox(),
            outbox(),
            outbox(processed_at=procesado),
            outbox(store_id="otra-tienda"),
        ]
    )
    await test_session.commit()

    res = await client.get("/ops/slo", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert set(cuerpo) == {
        "scope",
        "store_id",
        "status",
        "checked_at",
        "metrics",
        "thresholds",
        "alerts",
    }
    assert (cuerpo["scope"], cuerpo["store_id"], cuerpo["status"]) == (
        "store",
        store.id,
        "degraded",
    )
    assert cuerpo["metrics"] == {
        "pending_webhooks": 3,
        "failed_webhooks": 1,
        "pending_outbox": 2,
    }
    assert cuerpo["thresholds"] == {
        "pending_webhooks": 2,
        "failed_webhooks": 5,
        "pending_outbox": 1,
    }
    assert cuerpo["alerts"] == [
        {
            "code": "pending_webhooks_high",
            "severity": "critical",
            "value": 3,
            "threshold": 2,
        },
        {
            "code": "pending_outbox_high",
            "severity": "warning",
            "value": 2,
            "threshold": 1,
        },
    ]
