"""Presupuesto de sentencias SQL por endpoint caliente (F5-04, R11-21).

2026-09-24. Los cuellos de botella que encontro la auditoria de rendimiento
eran casi todos "mas sentencias de las necesarias" (identidad resuelta dos
veces, N+1 en listados, un ``SELECT`` por fila en reportes): nada de eso rompe
un test funcional, y la suite de SQLite ni siquiera ejecuta los ``set_config``
del contexto RLS. Este test cuenta, contra Postgres real y con datos de una
tienda con volumen (varios profesionales, servicios, turnos del dia, historial
de una semana, turnos de hoy, notificaciones), cuantas sentencias manda la app en cada
request caliente y falla si alguna pasa su techo.

Como se usa la tabla:
- Los numeros son un TECHO "<= hoy", medido en integration/aud2 @ 04bc98f.
  Bajarlos (Fase 3) es cambiar una linea; subirlos exige explicar en el PR que
  sentencia nueva hace falta y por que no se puede resolver con ``in_()``,
  join o cache (reglas 11 y 12).
- ``consultas`` son las sentencias de negocio; ``set_config`` se cuenta
  aparte porque es el costo fijo del contexto de tienda (RLS) y tiene su
  propio test (``test_identidad_una_vez_por_request``).
- Una ruta nueva bajo los prefijos calientes sin fila aca (ni en
  ``SIN_PRESUPUESTO`` con su motivo) hace fallar
  ``test_toda_ruta_caliente_tiene_presupuesto``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy import event, insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.database import _apply_tenant_context, set_tenant_context
from core.security import hash_password
from core.utils import local_to_utc, today_local
from main import app
from modules.appointments.model import Appointment
from modules.notifications.model import Notification
from modules.services.model import Service
from modules.staff.model import Schedule, Staff, StaffBlock, staff_services
from modules.stores.model import Store, StoreSchedule
from modules.users.model import User, UserRole
from tests.postgres.conftest import PASSWORD, auth_headers, seed_store_and_admin

pytestmark = pytest.mark.postgres


@dataclass(frozen=True)
class Presupuesto:
    consultas: int
    set_config: int


# Techo por request. Clave: "METODO /plantilla" (+ " [caso]" si la misma ruta
# se mide en dos estados). Medido el 2026-09-24 en integration/aud2 @ 04bc98f.
PRESUPUESTOS: dict[str, Presupuesto] = {
    "GET /public/stores/{slug}": Presupuesto(consultas=3, set_config=3),
    "GET /public/services": Presupuesto(consultas=3, set_config=3),
    "GET /public/staff": Presupuesto(consultas=5, set_config=3),
    "GET /public/availability [miss]": Presupuesto(consultas=11, set_config=3),
    "GET /public/availability [hit]": Presupuesto(consultas=2, set_config=3),
    "POST /public/appointments": Presupuesto(consultas=22, set_config=5),
    "GET /appointments/": Presupuesto(consultas=4, set_config=3),
    "GET /dashboard/summary": Presupuesto(consultas=12, set_config=3),
    "GET /reports/summary": Presupuesto(consultas=11, set_config=3),
    "GET /notifications": Presupuesto(consultas=3, set_config=3),
}

# Prefijos de las rutas calientes: el portal publico y las lecturas del panel
# que abre el dueno todo el dia.
PREFIJOS_CALIENTES = (
    "/public/",
    "/appointments/",
    "/dashboard/",
    "/reports/",
    "/notifications",
)

# Rutas bajo esos prefijos que HOY no tienen techo, con el motivo. Sacar una de
# aca y darle fila en PRESUPUESTOS es el camino; agregar una nueva aca exige
# decir por que no se mide.
SIN_PRESUPUESTO: dict[str, str] = {
    "GET /appointments/availability": "misma logica que la publica, ya medida",
    "GET /appointments/search": "busqueda con filtros; pendiente de Fase 3",
    "POST /appointments/": "alta desde el panel; la rafaga la cubre test_pg_reserva",
    "PATCH /appointments/{public_id}/absent": "transicion unitaria, fuera del camino caliente",
    "PATCH /appointments/{public_id}/cancel": "transicion unitaria, fuera del camino caliente",
    "PATCH /appointments/{public_id}/complete": "transicion unitaria, fuera del camino caliente",
    "PATCH /appointments/{public_id}/confirm": "transicion unitaria, fuera del camino caliente",
    "PATCH /appointments/{public_id}/notes-staff": "edicion unitaria",
    "PATCH /appointments/{public_id}/release": "transicion unitaria, fuera del camino caliente",
    "PATCH /appointments/{public_id}/reschedule": "transicion unitaria, fuera del camino caliente",
    "GET /reports/audit-logs": "paginado con tope 100; lectura de superadmin/dueno ocasional",
    "GET /reports/professionals": "agregado en SQL (test_reportes_dinero_en_sql)",
    "GET /reports/trend": "agregado en SQL (test_pg_tendencia_mes_local)",
    "POST /reports/export": "export fuera del p95 (plan-capacidad 5.2)",
    "POST /notifications/read-all": "UPDATE en SQL (test_notificaciones_read_all_en_sql)",
    "POST /notifications/{notification_id}/read": "UPDATE unitario",
    "GET /public/client/{store_public_id}/{phone}/appointments": "autogestion, requiere OTP",
    "GET /public/deposit/preview": "una vez por reserva; pendiente de Fase 3",
    "GET /public/payments/{payment_public_id}/status": "sondeo del retorno de MP",
    "GET /public/promotions/preview": "solo con codigo de promocion",
    "PATCH /public/client/appointments/{public_id}/cancel": "autogestion, requiere OTP",
    "PATCH /public/client/appointments/{public_id}/reschedule": "autogestion, requiere OTP",
    "POST /public/otp/request": "limitado por telefono y por IP",
    "POST /public/otp/verify": "limitado por telefono y por IP",
    "POST /public/waitlist": "anonimo con topes (test_lista_de_espera_acaparamiento)",
    "POST /public/waitlist/mine": "autogestion, requiere OTP",
    "POST /public/waitlist/{entry_id}/leave": "autogestion, requiere OTP",
}

MEDIR = os.getenv("PRESUPUESTO_MEDIR") == "1"


def _es_set_config(sql: str) -> bool:
    return "set_config(" in sql.lower()


@dataclass
class Conteo:
    sentencias: list[str] = field(default_factory=list)

    @property
    def set_config(self) -> int:
        return sum(1 for s in self.sentencias if _es_set_config(s))

    @property
    def consultas(self) -> int:
        return len(self.sentencias) - self.set_config


@contextmanager
def contar(engine: AsyncEngine) -> Iterator[Conteo]:
    conteo = Conteo()

    def registrar(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        executemany: bool,
    ) -> None:
        conteo.sentencias.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", registrar)
    try:
        yield conteo
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", registrar)


@dataclass(frozen=True)
class Tienda:
    slug: str
    store_public_id: str
    service_ids: list[str]
    staff_ids: list[str]
    dia: date
    slot_libre: datetime


SLUG = "presupuesto"
ADMIN_EMAIL = "presupuesto@demo.com"
PROFESIONALES = 3
SERVICIOS = 4
TURNOS_DEL_DIA = 6
# Turnos de HOY: el dashboard corta por el dia local de hoy y sin ellos
# mediria un dia vacio (revision de perf/f5, 2026-09-24).
ESTADOS_DE_HOY = ("completed", "confirmed", "confirmed", "pending")
DIAS_DE_HISTORIAL = 7
TURNOS_POR_DIA_PASADO = 4
NOTIFICACIONES = 12


async def _tienda_con_volumen(sessions: async_sessionmaker[AsyncSession]) -> Tienda:
    """Tienda con volumen realista, escrita con el rol de la app en bypass.

    Mismo camino que ``seed_store_and_admin`` y ``scripts/seed_simulation``:
    RLS esta forzada, asi que se escribe con contexto de superadmin explicito.
    """
    store_public_id = await seed_store_and_admin(sessions, slug=SLUG, email=ADMIN_EMAIL)
    dia = today_local() + timedelta(days=1)
    async with sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            store = (
                await session.execute(
                    Store.__table__.select().where(Store.public_id == store_public_id)
                )
            ).one()
            store_id = str(store.id)
            for dow in range(7):
                session.add(
                    StoreSchedule(
                        store_id=store_id,
                        day_of_week=dow,
                        open_time=time(8, 0),
                        close_time=time(20, 0),
                    )
                )
            servicios = []
            for i in range(SERVICIOS):
                servicio = Service(
                    store_id=store_id,
                    name=f"Servicio {i}",
                    description="Servicio de prueba",
                    duration_minutes=30,
                    price=Decimal(10000 + 1000 * i),
                    is_active=True,
                )
                session.add(servicio)
                servicios.append(servicio)
            await session.flush()
            profesionales = []
            for i in range(PROFESIONALES):
                profesional = Staff(
                    store_id=store_id,
                    first_name=f"Pro{i}",
                    last_name="Demo",
                    display_name=f"Pro {i}",
                    email=f"pro{i}-{SLUG}@demo.com",
                    is_active=True,
                )
                session.add(profesional)
                profesionales.append(profesional)
            await session.flush()
            for profesional in profesionales:
                for servicio in servicios:
                    await session.execute(
                        insert(staff_services).values(
                            staff_id=profesional.id, service_id=servicio.id
                        )
                    )
                for dow in range(7):
                    session.add(
                        Schedule(
                            staff_id=profesional.id,
                            store_id=store_id,
                            day_of_week=dow,
                            start_time=time(8, 0),
                            end_time=time(20, 0),
                        )
                    )
            clientes = []
            for i in range(5):
                cliente = User(
                    email=f"cliente{i}-{SLUG}@demo.com",
                    hashed_password=hash_password(PASSWORD),
                    first_name=f"Cliente{i}",
                    last_name="Demo",
                    full_name=f"Cliente{i} Demo",
                    phone=f"+5491155{i:06d}",
                    role=UserRole.CLIENT,
                    store_id=store_id,
                )
                session.add(cliente)
                clientes.append(cliente)
            await session.flush()

            def turno(n: int, inicio: datetime, estado: str) -> Appointment:
                cliente = clientes[n % len(clientes)]
                servicio = servicios[n % len(servicios)]
                terminado = estado in {"completed", "absent"}
                return Appointment(
                    store_id=store_id,
                    staff_id=profesionales[n % len(profesionales)].id,
                    service_id=servicio.id,
                    client_id=cliente.id,
                    client_name=cliente.full_name,
                    client_email=cliente.email,
                    client_phone=cliente.phone,
                    starts_at=inicio,
                    ends_at=inicio + timedelta(minutes=30),
                    duration_minutes=30,
                    price_amount=servicio.price,
                    status=estado,
                    completed_at=inicio + timedelta(minutes=30) if terminado else None,
                    idempotency_key=f"{SLUG}-{n}",
                )

            n = 0
            # Turnos del dia medido: distintos profesionales y estados.
            for i in range(TURNOS_DEL_DIA):
                estado = "confirmed" if i % 2 else "pending"
                session.add(turno(n, local_to_utc(dia, time(9 + i, 0)), estado))
                n += 1
            hoy = today_local()
            for i, estado in enumerate(ESTADOS_DE_HOY):
                session.add(turno(n, local_to_utc(hoy, time(9 + i, 0)), estado))
                n += 1
            # Historial de la semana: completados, cancelados y ausentes.
            estados_pasados = ("completed", "completed", "cancelled", "absent")
            for atras in range(1, DIAS_DE_HISTORIAL + 1):
                pasado = today_local() - timedelta(days=atras)
                for j in range(TURNOS_POR_DIA_PASADO):
                    session.add(
                        turno(
                            n,
                            local_to_utc(pasado, time(10 + j, 0)),
                            estados_pasados[j % len(estados_pasados)],
                        )
                    )
                    n += 1
            session.add(
                StaffBlock(
                    store_id=store_id,
                    staff_id=profesionales[0].id,
                    start_time=local_to_utc(dia, time(16, 0)),
                    end_time=local_to_utc(dia, time(17, 0)),
                    reason="Tramite",
                    is_active=True,
                )
            )
            for i in range(NOTIFICACIONES):
                session.add(
                    Notification(
                        store_id=store_id,
                        type="appointment_created",
                        title=f"Reserva nueva {i}",
                        body="Turno reservado desde la web",
                        read_at=datetime.now(timezone.utc) if i % 3 == 0 else None,
                    )
                )
            await session.flush()
            servicio_ids = [str(s.public_id) for s in servicios]
            staff_ids = [str(p.public_id) for p in profesionales]
            await session.commit()
        finally:
            set_tenant_context(None, False)
    return Tienda(
        slug=SLUG,
        store_public_id=store_public_id,
        service_ids=servicio_ids,
        staff_ids=staff_ids,
        dia=dia,
        slot_libre=local_to_utc(dia, time(18, 0)),
    )


def test_toda_ruta_caliente_tiene_presupuesto() -> None:
    """Una ruta nueva del portal o del panel caliente no entra sin decidir."""
    medidas = {clave.split(" [")[0] for clave in PRESUPUESTOS}
    rutas = {
        f"{metodo} {ruta.path}"
        for ruta in app.routes
        if isinstance(ruta, APIRoute) and ruta.path.startswith(PREFIJOS_CALIENTES)
        for metodo in ruta.methods
    }

    sin_fila = sorted(rutas - medidas - set(SIN_PRESUPUESTO))
    assert not sin_fila, (
        "Rutas calientes sin presupuesto de sentencias: agregar su fila en "
        f"PRESUPUESTOS (medida) o en SIN_PRESUPUESTO (con motivo): {sin_fila}"
    )
    fantasmas = sorted((medidas | set(SIN_PRESUPUESTO)) - rutas)
    assert not fantasmas, f"Filas de rutas que ya no existen: {fantasmas}"
    assert not medidas & set(SIN_PRESUPUESTO), "una ruta no puede estar en las dos"


@pytest.mark.asyncio
async def test_los_endpoints_calientes_no_pasan_su_presupuesto(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
) -> None:
    tienda = await _tienda_con_volumen(app_sessions)
    login = await client.post(
        "/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    panel = auth_headers(str(login.json()["access_token"]))
    dia = tienda.dia.isoformat()
    tienda_q = {"store_public_id": tienda.store_public_id}
    disponibilidad = {**tienda_q, "service_id": tienda.service_ids[0], "date": dia}

    # (clave, metodo, url, params, json, headers, codigo esperado). El orden
    # importa: la disponibilidad se pide dos veces (cache frio y caliente) y
    # la reserva va al final porque cambia la agenda.
    pedidos: list[tuple[str, str, str, dict[str, Any], Any, dict[str, str], int]] = [
        (
            "GET /public/stores/{slug}",
            "GET",
            f"/public/stores/{SLUG}",
            {},
            None,
            {},
            200,
        ),
        ("GET /public/services", "GET", "/public/services", tienda_q, None, {}, 200),
        ("GET /public/staff", "GET", "/public/staff", tienda_q, None, {}, 200),
        (
            "GET /public/availability [miss]",
            "GET",
            "/public/availability",
            disponibilidad,
            None,
            {},
            200,
        ),
        (
            "GET /public/availability [hit]",
            "GET",
            "/public/availability",
            disponibilidad,
            None,
            {},
            200,
        ),
        (
            "GET /appointments/",
            "GET",
            "/appointments/",
            {"date": dia},
            None,
            panel,
            200,
        ),
        ("GET /dashboard/summary", "GET", "/dashboard/summary", {}, None, panel, 200),
        (
            "GET /reports/summary",
            "GET",
            "/reports/summary",
            {
                "from_date": (today_local() - timedelta(days=6)).isoformat(),
                "to_date": today_local().isoformat(),
            },
            None,
            panel,
            200,
        ),
        ("GET /notifications", "GET", "/notifications", {}, None, panel, 200),
        (
            "POST /public/appointments",
            "POST",
            "/public/appointments",
            {},
            {
                "store_public_id": tienda.store_public_id,
                "service_id": tienda.service_ids[0],
                "staff_id": tienda.staff_ids[1],
                "starts_at": tienda.slot_libre.isoformat(),
                "client_name": "Cliente Presupuesto",
                "client_phone": "+5491166600001",
                "accepts_terms": True,
                "idempotency_key": "presupuesto-reserva-1",
            },
            {},
            201,
        ),
    ]

    medidos: dict[str, Conteo] = {}
    for clave, metodo, url, params, cuerpo, headers, esperado in pedidos:
        with contar(app_engine) as conteo:
            respuesta = await client.request(
                metodo, url, params=params, json=cuerpo, headers=headers
            )
        assert respuesta.status_code == esperado, (clave, respuesta.text[:300])
        medidos[clave] = conteo

    assert set(medidos) == set(PRESUPUESTOS), "cada fila de la tabla se mide"
    tabla = "\n".join(
        f"  {clave:<34} consultas={c.consultas:>3} (techo "
        f"{PRESUPUESTOS[clave].consultas:>3})  set_config={c.set_config:>2} "
        f"(techo {PRESUPUESTOS[clave].set_config:>2})"
        for clave, c in medidos.items()
    )
    if MEDIR:
        print("\nSentencias por request:\n" + tabla)
        for clave, c in medidos.items():
            print(f"\n--- {clave}")
            for s in c.sentencias:
                print("   ", " ".join(s.split())[:160])
    excedidos = [
        clave
        for clave, c in medidos.items()
        if c.consultas > PRESUPUESTOS[clave].consultas
        or c.set_config > PRESUPUESTOS[clave].set_config
    ]
    assert not excedidos, (
        f"Pasaron su presupuesto de sentencias: {excedidos}\n{tabla}\n"
        "Si la sentencia nueva es necesaria, subir el techo en el mismo PR y "
        "explicar por que no se resuelve con in_(), join o cache (reglas 11-12)."
    )
