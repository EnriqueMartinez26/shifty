"""Agenda del panel: quien cancela o reprograma, y con que horario (2026-09-29).

Sintomas (analisis de agenda, 2026-09-29):

- ``PATCH /appointments/{id}/cancel`` y ``/reschedule`` no miraban el rol ni
  el duenio del turno: cualquier usuario autenticado de la tienda (un
  profesional cualquiera) cancelaba o movia el turno de otro profesional.
- Reprogramar desde el panel no validaba la jornada del profesional: un turno
  se movia a las 03:00 sin que nadie lo decidiera.
- Cancelar un turno que ya habia empezado lo "soltaba" (y publicaba el cupo
  liberado) cuando lo que corresponde es completarlo o marcar la ausencia.
- Un profesional sin franjas cargadas no tenia agenda: la disponibilidad y el
  alta solo miraban ``schedules`` y no caian al horario comercial del local.

Decisiones del duenio que fija este archivo (docs/DECISIONES.md):
D-20260929-01 y -02 (horario efectivo con respaldo del local, tambien en el
backend), -03 (quien cancela/reprograma), -04 (fuera de horario solo el admin,
explicito) y -05 (un turno empezado no se cancela desde el panel).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import ARGENTINA_TZ
from tests.integration.test_alta_del_panel_para_cliente import (
    Agenda,
    _agenda,
    _reservar,
    _usuario,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_staff,
)

DIAS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


async def _segundo_profesional(
    client: AsyncClient, agenda: Agenda, slug: str, *, con_franja: bool = True
) -> str:
    staff = await create_staff(
        client, agenda.token, agenda.service, email=f"pro2-{slug}@t.com"
    )
    if con_franja:
        await add_staff_schedule(client, agenda.token, staff, target_date=agenda.slot)
    return staff


async def _turno_de(
    client: AsyncClient, agenda: Agenda, staff: str, inicio: datetime, clave: str
) -> str:
    res = await _reservar(
        client,
        agenda,
        staff_id=staff,
        starts_at=inicio.isoformat(),
        idempotency_key=f"agenda-turno-{clave}",
        allow_outside_schedule=True,
    )
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


async def _cancelar(client: AsyncClient, turno: str, token: str) -> Any:
    return await client.patch(
        f"/appointments/{turno}/cancel", headers=auth_headers(token)
    )


async def _reprogramar(
    client: AsyncClient, turno: str, token: str, inicio: datetime, **extra: Any
) -> Any:
    cuerpo: dict[str, Any] = {
        "new_starts_at": inicio.isoformat(),
        "idempotency_key": f"repro-{turno}-{inicio.isoformat()}-{len(extra)}",
    }
    cuerpo.update(extra)
    return await client.patch(
        f"/appointments/{turno}/reschedule", headers=auth_headers(token), json=cuerpo
    )


# ---------------------------------------------------------------------------
# D-20260929-03: rol y duenio del turno
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_profesional_solo_cancela_sus_propios_turnos(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    agenda = await _agenda(client, "ag-cancel-pro")
    otro = await _segundo_profesional(client, agenda, "ag-cancel-pro")
    del_otro = await _turno_de(client, agenda, otro, agenda.slot, "c1")
    propio = await _turno_de(
        client, agenda, agenda.staff, agenda.slot + timedelta(hours=2), "c2"
    )
    token_pro = await _usuario(
        client,
        test_session,
        agenda,
        email="pro-ag-cancel-pro@t.com",
        role="staff",
        user_id=agenda.staff,
    )

    ajeno = await _cancelar(client, del_otro, token_pro)
    assert ajeno.status_code == 403, ajeno.text
    assert ajeno.json()["error_code"] == "PERMISSION_DENIED"

    suyo = await _cancelar(client, propio, token_pro)
    assert suyo.status_code == 200, suyo.text
    assert suyo.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_recepcion_y_admin_cancelan_cualquier_turno_de_la_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    agenda = await _agenda(client, "ag-cancel-rec")
    otro = await _segundo_profesional(client, agenda, "ag-cancel-rec")
    uno = await _turno_de(client, agenda, otro, agenda.slot, "r1")
    dos = await _turno_de(
        client, agenda, agenda.staff, agenda.slot + timedelta(hours=2), "r2"
    )
    token_rec = await _usuario(
        client,
        test_session,
        agenda,
        email="rec-ag-cancel@t.com",
        role="receptionist",
    )

    assert (await _cancelar(client, uno, token_rec)).status_code == 200
    assert (await _cancelar(client, dos, agenda.token)).status_code == 200


@pytest.mark.asyncio
async def test_el_profesional_solo_reprograma_sus_propios_turnos(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    agenda = await _agenda(client, "ag-repro-pro")
    otro = await _segundo_profesional(client, agenda, "ag-repro-pro")
    del_otro = await _turno_de(client, agenda, otro, agenda.slot, "p1")
    propio = await _turno_de(
        client, agenda, agenda.staff, agenda.slot + timedelta(hours=1), "p2"
    )
    token_pro = await _usuario(
        client,
        test_session,
        agenda,
        email="pro-ag-repro-pro@t.com",
        role="staff",
        user_id=agenda.staff,
    )
    destino = agenda.slot + timedelta(hours=3)

    ajeno = await _reprogramar(client, del_otro, token_pro, destino)
    assert ajeno.status_code == 403, ajeno.text
    assert ajeno.json()["error_code"] == "PERMISSION_DENIED"

    suyo = await _reprogramar(client, propio, token_pro, destino)
    assert suyo.status_code == 200, suyo.text


# ---------------------------------------------------------------------------
# D-20260929-04: fuera de la jornada, solo el admin y explicito
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reprogramar_fuera_de_la_jornada_solo_el_admin_explicito(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    agenda = await _agenda(client, "ag-repro-horario")
    turno = await _turno_de(client, agenda, agenda.staff, agenda.slot, "h1")
    token_rec = await _usuario(
        client,
        test_session,
        agenda,
        email="rec-ag-horario@t.com",
        role="receptionist",
    )
    # 03:00 UTC del dia siguiente = 00:00 local: fuera de 06 a 18 local.
    fuera = agenda.slot.replace(hour=3) + timedelta(days=1)

    sin_permiso = await _reprogramar(client, turno, agenda.token, fuera)
    assert sin_permiso.status_code == 409, sin_permiso.text
    assert sin_permiso.json()["error_code"] == "OUT_OF_SCHEDULE"

    recepcion = await _reprogramar(
        client, turno, token_rec, fuera, allow_outside_schedule=True
    )
    assert recepcion.status_code == 403, recepcion.text
    assert recepcion.json()["error_code"] == "PERMISSION_DENIED"

    admin = await _reprogramar(
        client, turno, agenda.token, fuera, allow_outside_schedule=True
    )
    assert admin.status_code == 200, admin.text
    assert admin.json()["starts_at"].startswith(fuera.strftime("%Y-%m-%dT%H:%M"))


# ---------------------------------------------------------------------------
# D-20260929-05: un turno que ya empezo no se cancela desde el panel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_se_cancela_un_turno_que_ya_empezo(client: AsyncClient) -> None:
    agenda = await _agenda(client, "ag-empezado")
    empezado = await _turno_de(
        client,
        agenda,
        agenda.staff,
        datetime.now(timezone.utc) - timedelta(minutes=10),
        "e1",
    )

    res = await _cancelar(client, empezado, agenda.token)

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "APPOINTMENT_ALREADY_STARTED"


# ---------------------------------------------------------------------------
# D-20260929-01/02: horario efectivo con respaldo del horario del local
# ---------------------------------------------------------------------------


async def _horario_del_local(
    client: AsyncClient, token: str, dia: datetime, abre: str, cierra: str
) -> None:
    clave = DIAS[dia.astimezone(ARGENTINA_TZ).weekday()]
    res = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"business_hours": {clave: [{"open": abre, "close": cierra}]}},
    )
    assert res.status_code == 200, res.text


async def _slots_de(
    client: AsyncClient, agenda: Agenda, staff: str, dia: datetime
) -> list[str]:
    res = await client.get(
        "/appointments/availability",
        headers=auth_headers(agenda.token),
        params={
            "service_id": agenda.service,
            "date": dia.astimezone(ARGENTINA_TZ).date().isoformat(),
        },
    )
    assert res.status_code == 200, res.text
    return [s["start_time"] for s in res.json() if s["staff_id"] == staff]


@pytest.mark.asyncio
async def test_sin_franjas_el_profesional_usa_el_horario_del_local(
    client: AsyncClient,
) -> None:
    agenda = await _agenda(client, "ag-respaldo")
    sin_franjas = await _segundo_profesional(
        client, agenda, "ag-respaldo", con_franja=False
    )
    await _horario_del_local(client, agenda.token, agenda.slot, "09:00", "12:00")

    horas = await _slots_de(client, agenda, sin_franjas, agenda.slot)

    assert horas, "sin franjas propias tiene que heredar el horario del local"
    assert min(horas) == "09:00:00"
    assert max(horas) < "12:00:00"
    # El que SI tiene franjas sigue con las suyas (06 a 18 local).
    assert min(await _slots_de(client, agenda, agenda.staff, agenda.slot)) == (
        "06:00:00"
    )


@pytest.mark.asyncio
async def test_con_franjas_pero_ninguna_ese_dia_el_profesional_no_atiende(
    client: AsyncClient,
) -> None:
    agenda = await _agenda(client, "ag-cerrado")
    otro = await _segundo_profesional(client, agenda, "ag-cerrado", con_franja=False)
    # Una franja en OTRO dia: ya tiene agenda propia, y ese dia no atiende.
    await add_staff_schedule(
        client, agenda.token, otro, target_date=agenda.slot + timedelta(days=1)
    )
    await _horario_del_local(client, agenda.token, agenda.slot, "09:00", "12:00")

    assert await _slots_de(client, agenda, otro, agenda.slot) == []
    # 12:00 UTC = 09:00 local: dentro del horario del local, pero no el suyo.
    res = await _reservar(
        client,
        agenda,
        staff_id=otro,
        starts_at=agenda.slot.replace(hour=12).isoformat(),
        idempotency_key="agenda-cerrado-1",
    )
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "OUT_OF_SCHEDULE"


@pytest.mark.asyncio
async def test_alta_y_reprogramacion_validan_contra_el_horario_del_local(
    client: AsyncClient,
) -> None:
    agenda = await _agenda(client, "ag-respaldo-alta")
    sin_franjas = await _segundo_profesional(
        client, agenda, "ag-respaldo-alta", con_franja=False
    )
    await _horario_del_local(client, agenda.token, agenda.slot, "09:00", "12:00")
    # 12:00 UTC = 09:00 local (abre el local); 16:00 UTC = 13:00 (cerrado).
    dentro = agenda.slot.replace(hour=12)
    fuera = agenda.slot.replace(hour=16)

    alta = await _reservar(
        client,
        agenda,
        staff_id=sin_franjas,
        starts_at=dentro.isoformat(),
        idempotency_key="agenda-respaldo-alta-1",
    )
    assert alta.status_code == 201, alta.text
    rechazo = await _reservar(
        client,
        agenda,
        staff_id=sin_franjas,
        starts_at=fuera.isoformat(),
        idempotency_key="agenda-respaldo-alta-2",
    )
    assert rechazo.status_code == 409, rechazo.text
    assert rechazo.json()["error_code"] == "OUT_OF_SCHEDULE"

    turno = str(alta.json()["public_id"])
    movido = await _reprogramar(
        client, turno, agenda.token, dentro + timedelta(hours=1)
    )
    assert movido.status_code == 200, movido.text
    afuera = await _reprogramar(
        client, str(movido.json()["public_id"]), agenda.token, fuera
    )
    assert afuera.status_code == 409, afuera.text
    assert afuera.json()["error_code"] == "OUT_OF_SCHEDULE"


@pytest.mark.asyncio
async def test_el_alta_de_un_profesional_sin_franjas_invalida_la_agenda(
    client: AsyncClient,
) -> None:
    """Sin franjas el profesional atiende en el horario del local desde el
    alta: ``POST /staff/`` tiene que invalidar la agenda cacheada (antes no
    lo hacia porque un profesional nuevo no aportaba horarios)."""
    agenda = await _agenda(client, "ag-alta-invalida")
    await _horario_del_local(client, agenda.token, agenda.slot, "09:00", "12:00")
    # La agenda del dia queda en el cache sin el profesional nuevo.
    assert await _slots_de(client, agenda, agenda.staff, agenda.slot)

    nuevo = await _segundo_profesional(
        client, agenda, "ag-alta-invalida", con_franja=False
    )

    assert await _slots_de(client, agenda, nuevo, agenda.slot)
