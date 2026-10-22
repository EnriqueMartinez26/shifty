"""Limpieza de reservas del portal: origen del turno y cancelacion en bloque.

Paquete antiabuso (S5 y S6, 2026-10-22; pedido de Mateo, pendiente de OK del
dueno). Si un bot o una persona llena la agenda desde el portal publico, la
tienda necesita verlas juntas y soltarlas de una vez:

- ``appointments.booked_via``: ``portal`` | ``panel``. Todo lo que carga o
  mueve la tienda es ``panel`` (S5). La reserva publica escribe ``portal`` en
  ``public_api`` (fuera de este archivo); aca se marca a mano para probar los
  endpoints.
- ``GET /appointments/recent-portal?hours=`` (1..168, 72 por defecto): turnos
  futuros activos del portal creados en las ultimas N horas, el mas nuevo
  primero. Solo administradores de la tienda.
- ``POST /appointments/bulk-cancel``: cancela cada id por el mismo camino que
  la cancelacion de la agenda (lock turno -> pago, ``expire_live_charge``,
  auditoria, cupo liberado a la lista de espera) y ademas le avisa al cliente
  por el outbox. Lo que no se puede cancelar se saltea con su codigo.

Lo que SQLite no prueba (rafagas, RLS, el CHECK) va en
``tests/postgres/test_pg_limpieza_de_reservas_del_portal.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import ulid
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import modules.appointments.service as appointments_service
from core.availability_cache import invalidate_availability
from modules.appointments.model import Appointment
from modules.audit.model import AuditAction, AuditLog
from modules.billing.model import Plan, StoreSubscription
from modules.payments.model import OutboxMessage, PaymentStatus
from modules.stores.model import Store
from tests.integration.test_cancelar_desde_el_panel_vence_el_cobro import (
    _cobro,
    _con_sena,
    _personal,
    _tienda,
    _Tienda,
    _vencimientos,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)

MAIL_DE_CANCELACION = "appointment.cancelled_by_block"
CUPO_LIBERADO = "appointment.slot_released"


async def _alta_del_panel(
    client: AsyncClient, t: _Tienda, hora: int, *, email: str | None = None
) -> str:
    cuerpo: dict[str, Any] = {
        "service_id": t.service,
        "staff_id": t.staff,
        "starts_at": t.dia.replace(
            hour=hora, minute=0, second=0, microsecond=0
        ).isoformat(),
        "client_name": f"Cliente {hora}",
        "client_phone": f"+54911557{hora:05d}",
        "idempotency_key": f"limpieza-{t.store}-{hora}",
    }
    if email:
        cuerpo["client_email"] = email
    res = await client.post(
        "/appointments/", headers=auth_headers(t.admin), json=cuerpo
    )
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


async def _turno(session: AsyncSession, turno: str) -> Appointment:
    session.expire_all()
    return (
        await session.execute(select(Appointment).where(Appointment.id == turno))
    ).scalar_one()


async def _marcar(session: AsyncSession, turno: str, **valores: Any) -> None:
    """Cambia columnas a mano: el origen (lo escribe ``public_api``), la fecha
    de alta o el horario (un turno que ya empezo)."""
    await session.execute(
        update(Appointment).where(Appointment.id == turno).values(**valores)
    )
    await session.commit()


async def _eventos(session: AsyncSession, tipo: str) -> list[dict[str, Any]]:
    session.expire_all()
    filas = (
        await session.execute(
            select(OutboxMessage).where(OutboxMessage.event_type == tipo)
        )
    ).scalars()
    return [dict(f.payload or {}) for f in filas]


def _espiar_invalidacion(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    llamadas: list[tuple[str, ...]] = []
    original = invalidate_availability

    async def espia(cache: Any, store_id: str, *instantes: datetime) -> None:
        llamadas.append((store_id, *(i.isoformat() for i in instantes)))
        await original(cache, store_id, *instantes)

    monkeypatch.setattr(appointments_service, "invalidate_availability", espia)
    return llamadas


# ---------------------------------------------------------------------------
# S5: lo que carga o mueve la tienda es ``panel``
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_alta_y_la_reprogramacion_del_panel_quedan_como_panel(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "origen-panel", sena=False)
    alta = await _alta_del_panel(client, t, 12)
    assert (await _turno(test_session, alta)).booked_via == "panel"

    # Un turno del portal que la tienda mueve: el nuevo lo cargo la tienda.
    await _marcar(test_session, alta, booked_via="portal")
    movido = await client.patch(
        f"/appointments/{alta}/reschedule",
        headers=auth_headers(t.admin),
        json={
            "new_starts_at": t.dia.replace(
                hour=14, minute=0, second=0, microsecond=0
            ).isoformat(),
            "idempotency_key": f"origen-mover-{t.store}",
        },
    )

    assert movido.status_code == 200, movido.text
    nuevo = str(movido.json()["public_id"])
    assert nuevo != alta
    assert (await _turno(test_session, nuevo)).booked_via == "panel"


@pytest.mark.asyncio
async def test_un_insert_sin_origen_toma_el_default_panel(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un INSERT que no dice el origen es de la tienda (default de la columna)."""
    t = await _tienda(client, monkeypatch, "origen-default", sena=False)
    plantilla = await _turno(test_session, await _alta_del_panel(client, t, 9))
    nuevo = Appointment(
        id=str(ulid.ULID()),
        store_id=plantilla.store_id,
        staff_id=plantilla.staff_id,
        service_id=plantilla.service_id,
        client_id=plantilla.client_id,
        client_name="Sin origen",
        starts_at=plantilla.starts_at + timedelta(hours=6),
        ends_at=plantilla.ends_at + timedelta(hours=6),
        duration_minutes=plantilla.duration_minutes,
    )
    test_session.add(nuevo)
    await test_session.commit()

    assert (await _turno(test_session, nuevo.id)).booked_via == "panel"


# ---------------------------------------------------------------------------
# S6: GET /appointments/recent-portal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["staff", "receptionist"])
async def test_reservas_recientes_solo_para_administradores(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    rol: str,
) -> None:
    t = await _tienda(client, monkeypatch, f"recientes-rol-{rol}", sena=False)
    token = await _personal(client, t, rol, f"recientes-rol-{rol}")

    res = await client.get("/appointments/recent-portal", headers=auth_headers(token))

    assert res.status_code == 403, res.text
    assert res.json()["error_code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_reservas_recientes_lista_las_del_portal_futuras_activas_y_recientes(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "recientes-filtros", sena=False)
    ahora = datetime.now(timezone.utc)
    vieja = await _alta_del_panel(client, t, 9)
    nueva = await _alta_del_panel(client, t, 10)
    del_panel = await _alta_del_panel(client, t, 11)
    cancelada = await _alta_del_panel(client, t, 12)
    de_hace_cinco_dias = await _alta_del_panel(client, t, 13)
    empezada = await _alta_del_panel(client, t, 14)
    for turno in (vieja, nueva, cancelada, de_hace_cinco_dias, empezada):
        await _marcar(test_session, turno, booked_via="portal")
    await _marcar(test_session, vieja, created_at=ahora - timedelta(hours=10))
    await _marcar(test_session, nueva, created_at=ahora - timedelta(hours=1))
    await _marcar(
        test_session, de_hace_cinco_dias, created_at=ahora - timedelta(hours=120)
    )
    pasado = ahora - timedelta(hours=1)
    await _marcar(
        test_session, empezada, starts_at=pasado, ends_at=pasado + timedelta(hours=1)
    )
    res = await client.patch(
        f"/appointments/{cancelada}/cancel", headers=auth_headers(t.admin)
    )
    assert res.status_code == 200, res.text

    por_defecto = await client.get(
        "/appointments/recent-portal", headers=auth_headers(t.admin)
    )
    semana = await client.get(
        "/appointments/recent-portal",
        headers=auth_headers(t.admin),
        params={"hours": 168},
    )

    assert por_defecto.status_code == 200, por_defecto.text
    cuerpo = por_defecto.json()
    assert cuerpo["truncated"] is False
    assert [i["public_id"] for i in cuerpo["items"]] == [nueva, vieja]
    item = cuerpo["items"][0]
    assert item["client_name"] == "Cliente 10"
    assert item["client_phone"] == "5491155700010"
    assert item["service_name"]
    assert item["staff_name"]
    assert item["status"] == "confirmed"
    assert item["starts_at"] and item["created_at"]
    assert semana.status_code == 200, semana.text
    assert [i["public_id"] for i in semana.json()["items"]] == [
        nueva,
        vieja,
        de_hace_cinco_dias,
    ]
    assert del_panel not in {i["public_id"] for i in semana.json()["items"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("horas", [0, 169, -1])
async def test_reservas_recientes_rechaza_horas_fuera_de_rango(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    horas: int,
) -> None:
    t = await _tienda(client, monkeypatch, f"recientes-horas-{horas}", sena=False)

    res = await client.get(
        "/appointments/recent-portal",
        headers=auth_headers(t.admin),
        params={"hours": horas},
    )

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_reservas_recientes_no_muestra_las_de_otra_tienda(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    propia = await _tienda(client, monkeypatch, "recientes-propia", sena=False)
    ajena = await _tienda(client, monkeypatch, "recientes-ajena", sena=False)
    mia = await _alta_del_panel(client, propia, 10)
    de_otra = await _alta_del_panel(client, ajena, 10)
    for turno in (mia, de_otra):
        await _marcar(test_session, turno, booked_via="portal")

    res = await client.get(
        "/appointments/recent-portal", headers=auth_headers(propia.admin)
    )

    assert res.status_code == 200, res.text
    assert [i["public_id"] for i in res.json()["items"]] == [mia]


# ---------------------------------------------------------------------------
# S6: POST /appointments/bulk-cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancela_del_portal_y_del_panel_y_saltea_lo_que_no_puede(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "bulk-mixto", sena=False)
    ajena = await _tienda(client, monkeypatch, "bulk-mixto-ajena", sena=False)
    del_portal = await _alta_del_panel(client, t, 9, email="cliente-portal@example.com")
    await _marcar(test_session, del_portal, booked_via="portal")
    del_panel = await _alta_del_panel(client, t, 10)
    ya_cancelado = await _alta_del_panel(client, t, 11)
    empezado = await _alta_del_panel(client, t, 12)
    de_otra_tienda = await _alta_del_panel(client, ajena, 9)
    res = await client.patch(
        f"/appointments/{ya_cancelado}/cancel", headers=auth_headers(t.admin)
    )
    assert res.status_code == 200, res.text
    pasado = datetime.now(timezone.utc) - timedelta(minutes=30)
    await _marcar(
        test_session, empezado, starts_at=pasado, ends_at=pasado + timedelta(hours=1)
    )
    inexistente = str(ulid.ULID())
    inicio_portal = (await _turno(test_session, del_portal)).starts_at
    inicio_panel = (await _turno(test_session, del_panel)).starts_at
    liberados_antes = len(await _eventos(test_session, CUPO_LIBERADO))
    invalidaciones = _espiar_invalidacion(monkeypatch)

    res = await client.post(
        "/appointments/bulk-cancel",
        headers=auth_headers(t.admin),
        json={
            "appointment_ids": [
                del_portal,
                del_panel,
                ya_cancelado,
                empezado,
                inexistente,
                de_otra_tienda,
            ],
            "reason": "Reservas falsas",
        },
    )

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert sorted(cuerpo["cancelled"]) == sorted([del_portal, del_panel])
    assert {s["id"]: s["code"] for s in cuerpo["skipped"]} == {
        ya_cancelado: "APPOINTMENT_ALREADY_CANCELLED",
        empezado: "APPOINTMENT_ALREADY_STARTED",
        inexistente: "NOT_FOUND",
        de_otra_tienda: "NOT_FOUND",
    }
    for turno in (del_portal, del_panel):
        assert (await _turno(test_session, turno)).status == "cancelled"
    assert (await _turno(test_session, empezado)).status == "confirmed"
    assert (await _turno(test_session, de_otra_tienda)).status == "confirmed"
    # Auditoria y cupo liberado, como la cancelacion de la agenda.
    auditados = (
        await test_session.execute(
            select(AuditLog).where(
                AuditLog.action == AuditAction.STATUS_CHANGE,
                AuditLog.resource_id.in_([del_portal, del_panel]),
            )
        )
    ).scalars()
    despues: dict[str, dict[str, Any]] = {
        str(a.resource_id): dict(a.payload_after or {}) for a in auditados
    }
    assert set(despues) == {del_portal, del_panel}
    assert despues[del_portal]["status"] == "cancelled"
    assert despues[del_portal]["reason"] == "bulk_cancel"
    assert despues[del_portal]["cancel_reason"] == "Reservas falsas"
    liberados = await _eventos(test_session, CUPO_LIBERADO)
    assert len(liberados) - liberados_antes == 2
    # Aviso al cliente por el outbox, solo a quien tiene email entregable.
    mails = await _eventos(test_session, MAIL_DE_CANCELACION)
    assert [m["public_id"] for m in mails] == [del_portal]
    assert mails[0]["client_email"] == "cliente-portal@example.com"
    assert mails[0]["block_reason"] == "Reservas falsas"
    # Una sola invalidacion, con los dos horarios.
    assert len(invalidaciones) == 1, invalidaciones
    tienda, *instantes = invalidaciones[0]
    assert tienda == (await _turno(test_session, del_portal)).store_id
    assert sorted(instantes) == sorted(
        [inicio_portal.isoformat(), inicio_panel.isoformat()]
    )


@pytest.mark.asyncio
async def test_cancelar_en_bloque_vence_el_cobro_vivo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "bulk-sena", sena=True)
    turno = await _con_sena(client, t, 12)
    llamadas_antes = len(t.llamadas_mp)

    res = await client.post(
        "/appointments/bulk-cancel",
        headers=auth_headers(t.admin),
        json={"appointment_ids": [turno]},
    )

    assert res.status_code == 200, res.text
    assert res.json() == {"cancelled": [turno], "skipped": []}
    assert (await _cobro(test_session, turno)).status == PaymentStatus.EXPIRED.value
    assert len(await _vencimientos(test_session, turno)) == 1
    # Regla 5: ninguna llamada a MP en el request; el link lo vence el outbox.
    assert t.llamadas_mp[llamadas_antes:] == []
    mails = await _eventos(test_session, MAIL_DE_CANCELACION)
    assert [m["public_id"] for m in mails] == [turno]
    assert "block_reason" not in mails[0] or not mails[0]["block_reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cuerpo",
    [
        {"appointment_ids": []},
        {"appointment_ids": [str(ulid.ULID()) for _ in range(101)]},
        {"appointment_ids": ["DUPLICADO01", "DUPLICADO01"]},
        {"appointment_ids": ["no valido!"]},
        {"appointment_ids": ["ID01"], "reason": "x" * 201},
        {"appointment_ids": ["ID01"], "reason": "Motivo‮oculto"},
        {},
    ],
    ids=[
        "vacio",
        "101",
        "duplicados",
        "id-invalido",
        "motivo-largo",
        "bidi",
        "sin-ids",
    ],
)
async def test_cancelar_en_bloque_rechaza_el_cuerpo_invalido_sin_tocar_nada(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    cuerpo: dict[str, Any],
) -> None:
    t = await _tienda(client, monkeypatch, "bulk-invalido", sena=False)
    turno = await _alta_del_panel(client, t, 10)
    if cuerpo.get("appointment_ids") == ["ID01"]:
        cuerpo = {**cuerpo, "appointment_ids": [turno]}

    res = await client.post(
        "/appointments/bulk-cancel", headers=auth_headers(t.admin), json=cuerpo
    )

    assert res.status_code == 422, res.text
    assert (await _turno(test_session, turno)).status == "confirmed"


@pytest.mark.asyncio
async def test_cancelar_en_bloque_acepta_cien_ids(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, monkeypatch, "bulk-cien", sena=False)
    turno = await _alta_del_panel(client, t, 10)
    ids = [turno, *(str(ulid.ULID()) for _ in range(99))]

    res = await client.post(
        "/appointments/bulk-cancel",
        headers=auth_headers(t.admin),
        json={"appointment_ids": ids},
    )

    assert res.status_code == 200, res.text
    assert res.json()["cancelled"] == [turno]
    assert len(res.json()["skipped"]) == 99


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["staff", "receptionist"])
async def test_cancelar_en_bloque_solo_administradores(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    rol: str,
) -> None:
    t = await _tienda(client, monkeypatch, f"bulk-rol-{rol}", sena=False)
    token = await _personal(client, t, rol, f"bulk-rol-{rol}")
    turno = await _alta_del_panel(client, t, 10)

    res = await client.post(
        "/appointments/bulk-cancel",
        headers=auth_headers(token),
        json={"appointment_ids": [turno]},
    )

    assert res.status_code == 403, res.text
    assert res.json()["error_code"] == "PERMISSION_DENIED"
    assert (await _turno(test_session, turno)).status == "confirmed"


@pytest.mark.asyncio
async def test_la_cancelacion_de_la_agenda_sigue_sin_mail_al_cliente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La cancelacion de a uno no cambia: solo la limpieza en bloque avisa."""
    t = await _tienda(client, monkeypatch, "agenda-sin-mail", sena=False)
    turno = await _alta_del_panel(client, t, 10, email="agenda@example.com")

    res = await client.patch(
        f"/appointments/{turno}/cancel", headers=auth_headers(t.admin)
    )

    assert res.status_code == 200, res.text
    assert await _eventos(test_session, MAIL_DE_CANCELACION) == []


@pytest.mark.asyncio
async def test_con_la_tienda_suspendida_se_lista_pero_no_se_cancela_en_bloque(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La guarda de suspension del router (``block_writes_when_suspended``)
    cubre las dos rutas nuevas: el listado es una lectura y pasa; la
    cancelacion en bloque no esta en ``SUSPENSION_ALLOWED_WRITES``."""
    t = await _tienda(client, monkeypatch, "bulk-suspendida", sena=False)
    turno = await _alta_del_panel(client, t, 10)
    store_id = (
        await test_session.execute(select(Store.id).where(Store.public_id == t.store))
    ).scalar_one()
    plan = Plan(name="Plan suspendida", price=15000, currency="ARS")
    test_session.add(plan)
    await test_session.flush()
    ahora = datetime.now(timezone.utc)
    test_session.add(
        StoreSubscription(
            store_id=store_id,
            plan_id=plan.id,
            plan_name=plan.name,
            status="suspended",
            base_amount=plan.price,
            discount_amount=0,
            total_amount=plan.price,
            currency="ARS",
            current_period_start=ahora - timedelta(days=40),
            current_period_end=ahora - timedelta(days=10),
        )
    )
    await test_session.commit()

    lista = await client.get(
        "/appointments/recent-portal", headers=auth_headers(t.admin)
    )
    bloque = await client.post(
        "/appointments/bulk-cancel",
        headers=auth_headers(t.admin),
        json={"appointment_ids": [turno]},
    )

    assert lista.status_code == 200, lista.text
    assert bloque.status_code == 402, bloque.text
    assert bloque.json()["error_code"] == "SUBSCRIPTION_SUSPENDED"
    assert (await _turno(test_session, turno)).status == "confirmed"
