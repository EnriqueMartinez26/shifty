"""Rafagas concurrentes de reserva publica sobre el MISMO turno.

Prueba lo que ninguna secuencia de requests puede probar: que el lock
pesimista sobre el profesional + la exclusion GiST dejan pasar UNA reserva
y rechazan el resto con 409, sin ningun 5xx y sin dos filas activas en la
base. Corre con una sesion por request contra Postgres real; en SQLite el
mismo test seria una mentira (no hay concurrencia ni exclusion).
"""

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import pytest
from typing import cast
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.config import settings
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

RAFAGA = int(os.getenv("TEST_POSTGRES_RAFAGA", "25"))


async def _tienda_reservable(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str, str, datetime]:
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)
    return store, service, staff, slot


def _reserva(
    store: str, service: str, staff: str, slot: datetime, i: int, key: str
) -> dict[str, str]:
    return {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": f"Cliente {i}",
        "client_phone": f"+54911555{i:05d}",
        "accepts_terms": True,
        "idempotency_key": key,
    }


async def _turnos_activos(owner_engine: AsyncEngine, staff: str) -> int:
    async with owner_engine.connect() as conn:
        total = (
            await conn.execute(
                text(
                    "select count(*) from appointments "
                    "where staff_id = :staff "
                    "and status in ('pending','pending_payment','confirmed')"
                ),
                {"staff": staff},
            )
        ).scalar_one()
        return cast(int, total)


@pytest.mark.asyncio
async def test_rafaga_mismo_slot_deja_pasar_una_sola_reserva(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, service, staff, slot = await _tienda_reservable(
        client, app_sessions, "rafaga"
    )

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments",
                json=_reserva(store, service, staff, slot, i, f"pg-rafaga-{i:02d}"),
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(201) == 1, codigos
    assert set(codigos) <= {201, 409}, codigos
    assert await _turnos_activos(owner_engine, staff) == 1


@pytest.mark.asyncio
async def test_rafaga_con_la_misma_idempotency_key_crea_un_solo_turno(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    # Reintentos de red: el mismo cliente manda 30 veces la misma reserva.
    store, service, staff, slot = await _tienda_reservable(client, app_sessions, "idem")
    cuerpo = _reserva(store, service, staff, slot, 1, "idem-misma-clave")

    respuestas = await asyncio.gather(
        *(client.post("/public/appointments", json=cuerpo) for _ in range(30))
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    creados = {r.json()["public_id"] for r in respuestas if r.status_code == 201}
    assert len(creados) <= 1, creados
    assert await _turnos_activos(owner_engine, staff) == 1


@pytest.mark.asyncio
async def test_slots_distintos_no_se_bloquean_entre_si(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    # El lock es por profesional, no global: N slots distintos en paralelo
    # deben entrar todos (el servicio dura 30 minutos).
    store, service, staff, slot = await _tienda_reservable(
        client, app_sessions, "paralelo"
    )
    slots = [slot + timedelta(minutes=30 * i) for i in range(6)]

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments",
                json=_reserva(store, service, staff, s, i, f"pg-paralelo-{i:02d}"),
            )
            for i, s in enumerate(slots)
        )
    )
    codigos = [r.status_code for r in respuestas]

    assert codigos == [201] * len(slots), [
        (c, r.text[:120]) for c, r in zip(codigos, respuestas)
    ]
    assert await _turnos_activos(owner_engine, staff) == len(slots)


@pytest.mark.asyncio
async def test_rafaga_con_cualquier_profesional_llena_cada_agenda_una_sola_vez(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """B1-13 (2026-09-18): el alta con "cualquier profesional" lee en lote.

    Horarios, bloqueos y choques de todos los candidatos se leen sin lock y
    solo se lockea al elegido, con relectura bajo el lock (regla 4). Si la
    relectura faltara, dos requests que vieron libre al mismo profesional
    chocarian contra la exclusion GiST en vez de pasar al siguiente: con dos
    profesionales y una rafaga sobre el mismo slot tiene que haber
    EXACTAMENTE dos reservas (una por agenda), el resto 409 y cero 5xx.
    """
    store, token = await register_and_login(
        client, app_sessions, slug="cualquiera", email="cualquiera@demo.com"
    )
    service = await create_service(client, token)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    staffs: list[str] = []
    for nombre in ("uno", "dos"):
        staff = await create_staff(
            client, token, service, email=f"pro-{nombre}-cualquiera@demo.com"
        )
        await add_staff_schedule(client, token, staff, target_date=dia)
        staffs.append(staff)
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)

    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments",
                json={
                    **_reserva(
                        store, service, staffs[0], slot, i, f"pg-cualquiera-{i:02d}"
                    ),
                    "staff_id": None,
                },
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(201) == 2, codigos
    assert set(codigos) <= {201, 409}, codigos
    elegidos = sorted(r.json()["staff_id"] for r in respuestas if r.status_code == 201)
    assert elegidos == sorted(staffs), elegidos
    for staff in staffs:
        assert await _turnos_activos(owner_engine, staff) == 1


# ---------------------------------------------------------------------------
# Audit B1-17 (2026-09-18): rafagas sobre los endpoints que reprograman y
# liberan. Reprogramar cancela un turno y crea otro (reserva y cambia estado)
# y liberar cambia estado: CLAUDE.md §4 exige para todos "N identicas y N
# sobre el mismo slot a la vez: 1 exito, N-1 conflictos, cero 5xx". Ninguno
# la tenia. Misma estructura que las rafagas del alta, parametrizada por
# endpoint (panel / cliente). La liberacion se prueba sobre un turno sin cobro
# vivo: la que vence una preferencia de Mercado Pago es el camino de B1-04.
# ---------------------------------------------------------------------------

RAFAGA_REPROGRAMACION = min(RAFAGA, 10)
TELEFONO_CLIENTE = "+5491155570001"

Reprogramar = Callable[[str, datetime, str], Awaitable[Response]]


async def _originales(
    client: AsyncClient,
    *,
    via: str,
    store: str,
    token: str,
    service: str,
    staff: str,
    dia: datetime,
    cantidad: int,
) -> list[str]:
    """``cantidad`` turnos del mismo cliente, desde las 09:00 UTC cada 30 minutos."""
    turnos: list[str] = []
    for i in range(cantidad):
        inicio = dia.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(
            minutes=30 * i
        )
        if via == "panel":
            res = await client.post(
                "/appointments/",
                headers=auth_headers(token),
                json={
                    "service_id": service,
                    "staff_id": staff,
                    "starts_at": inicio.isoformat(),
                    "idempotency_key": f"pg-orig-{via}-{i:03d}",
                },
            )
        else:
            res = await client.post(
                "/public/appointments",
                json={
                    "store_public_id": store,
                    "service_id": service,
                    "staff_id": staff,
                    "starts_at": inicio.isoformat(),
                    "client_name": "Reprogramador",
                    # La autogestion exige una ficha con email ENTREGABLE verificado por
                    # OTP (2026-09-20): sin email la ficha queda con el tecnico `.noreply`.
                    "client_email": "reprogramador@example.com",
                    "client_phone": TELEFONO_CLIENTE,
                    "accepts_terms": True,
                    "idempotency_key": f"pg-orig-{via}-{i:03d}",
                },
            )
        assert res.status_code == 201, res.text
        turnos.append(str(res.json()["public_id"]))
    return turnos


async def _verificar_otp(client: AsyncClient, store: str) -> None:
    pedido = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": store,
            "phone": TELEFONO_CLIENTE,
            "channel": "whatsapp",
        },
    )
    assert pedido.status_code == 200, pedido.text
    verificado = await client.post(
        "/public/otp/verify",
        json={
            "store_public_id": store,
            "phone": TELEFONO_CLIENTE,
            "code": pedido.json()["debug_code"],
        },
    )
    assert verificado.status_code == 200, verificado.text


async def _preparar_reprogramacion(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    *,
    via: str,
    cantidad: int,
) -> tuple[list[str], str, datetime, Reprogramar]:
    """Tienda con ``cantidad`` turnos y el endpoint de reprogramar de ``via``."""
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    slug = f"repro-rafaga-{via}"
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    turnos = await _originales(
        client,
        via=via,
        store=store,
        token=token,
        service=service,
        staff=staff,
        dia=dia,
        cantidad=cantidad,
    )
    # Destino: 16:00 UTC (13:00 local), lejos de todos los originales.
    destino = dia.replace(hour=16, minute=0, second=0, microsecond=0)

    if via == "panel":

        async def reprogramar(turno: str, inicio: datetime, clave: str) -> Response:
            return await client.patch(
                f"/appointments/{turno}/reschedule",
                headers=auth_headers(token),
                json={"new_starts_at": inicio.isoformat(), "idempotency_key": clave},
            )

        return turnos, staff, destino, reprogramar

    await _verificar_otp(client, store)

    async def reprogramar_cliente(turno: str, inicio: datetime, clave: str) -> Response:
        return await client.patch(
            f"/public/client/appointments/{turno}/reschedule",
            json={
                "phone": TELEFONO_CLIENTE,
                "new_starts_at": inicio.isoformat(),
                "idempotency_key": clave,
            },
        )

    return turnos, staff, destino, reprogramar_cliente


async def _activos_en(owner_engine: AsyncEngine, staff: str, inicio: datetime) -> int:
    async with owner_engine.connect() as conn:
        total = (
            await conn.execute(
                text(
                    "select count(*) from appointments "
                    "where staff_id = :staff and starts_at = :inicio "
                    "and status in ('pending','pending_payment','confirmed')"
                ),
                {"staff": staff, "inicio": inicio},
            )
        ).scalar_one()
        return cast(int, total)


@pytest.mark.asyncio
@pytest.mark.parametrize("via", ["panel", "cliente"])
async def test_rafaga_de_reprogramaciones_identicas_crea_un_solo_turno(
    via: str,
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reintentos de red: la MISMA reprogramacion (misma clave) N veces."""
    turnos, staff, destino, reprogramar = await _preparar_reprogramacion(
        client, app_sessions, monkeypatch, via=via, cantidad=1
    )

    respuestas = await asyncio.gather(
        *(
            reprogramar(turnos[0], destino, f"pg-repro-idem-{via}")
            for _ in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert set(codigos) <= {200, 409}, codigos
    creados = {r.json()["public_id"] for r in respuestas if r.status_code == 200}
    assert len(creados) == 1, creados
    assert await _activos_en(owner_engine, staff, destino) == 1
    # El original quedo cancelado una sola vez: ningun otro turno activo.
    assert await _turnos_activos(owner_engine, staff) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("via", ["panel", "cliente"])
async def test_rafaga_de_reprogramaciones_al_mismo_slot_deja_pasar_una(
    via: str,
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N turnos distintos se reprograman a la vez al MISMO horario."""
    turnos, staff, destino, reprogramar = await _preparar_reprogramacion(
        client, app_sessions, monkeypatch, via=via, cantidad=RAFAGA_REPROGRAMACION
    )

    respuestas = await asyncio.gather(
        *(
            reprogramar(turno, destino, f"pg-repro-slot-{via}-{i:03d}")
            for i, turno in enumerate(turnos)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(200) == 1, codigos
    assert set(codigos) <= {200, 409}, codigos
    assert await _activos_en(owner_engine, staff, destino) == 1
    # Los perdedores conservan su turno original: nadie quedo sin turno.
    assert await _turnos_activos(owner_engine, staff) == len(turnos)


@pytest.mark.asyncio
async def test_rafaga_de_liberaciones_libera_una_sola_vez(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """N ``PATCH /release`` sobre el mismo turno pendiente: 1 exito, N-1 409."""
    store, token = await register_and_login(
        client, app_sessions, slug="release-rafaga", email="release-rafaga@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(
        client, token, service, email="pro-release-rafaga@demo.com"
    )
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)
    reserva = await client.post(
        "/public/appointments",
        json=_reserva(store, service, staff, slot, 1, "pg-release-rafaga"),
    )
    assert reserva.status_code == 201, reserva.text
    turno = reserva.json()["public_id"]

    respuestas = await asyncio.gather(
        *(
            client.patch(f"/appointments/{turno}/release", headers=auth_headers(token))
            for _ in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(200) == 1, codigos
    assert set(codigos) <= {200, 409}, codigos
    assert await _turnos_activos(owner_engine, staff) == 0
