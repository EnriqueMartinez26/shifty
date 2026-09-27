"""Editar un bloqueo que libera agenda le avisa a la lista de espera.

Audit B1-18 (2026-09-18), bloque "Lista de espera" de CLAUDE.md. Sintoma:
``DELETE /appointment-blocks/{id}`` publicaba ``appointment.slot_released``
pero ``PATCH`` con ``{"is_active": false}`` (el mismo estado final en la base)
no publicaba nada, y achicar o mover el rango tampoco: el tramo que quedaba
libre no le llegaba a nadie de la lista. Ahora hay un unico punto que compara
el bloqueo antes y despues y publica lo liberado; ``delete`` es el caso
``is_active=False``.

Guarda que se conserva: el motivo sigue siendo ``block_deleted`` (en
``RANGOS_SIN_GRILLA``), asi que un rango liberado se le avisa al duenio y NO
se le ofrece al cliente un horario fuera de grilla
(``ReleasedSlot.aligned_to_grid``).
"""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from core.utils import ensure_utc_aware
from modules.notifications.model import Notification
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage
from modules.waitlist.events import EVENT_SLOT_RELEASED
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_lista_de_espera import _alta, _entrada, _tienda
from tests.integration.test_mails_al_cliente import Buzon


async def _liberados(session: AsyncSession) -> list[tuple[datetime, datetime, str]]:
    session.expire_all()
    filas = await session.execute(
        select(OutboxMessage)
        .where(OutboxMessage.event_type == EVENT_SLOT_RELEASED)
        .order_by(OutboxMessage.created_at.asc())
    )
    return [
        (
            ensure_utc_aware(datetime.fromisoformat(str(m.payload["starts_at"]))),
            ensure_utc_aware(datetime.fromisoformat(str(m.payload["ends_at"]))),
            str(m.payload["reason"]),
        )
        for m in filas.scalars()
    ]


async def _bloquear(
    client: AsyncClient, token: str, staff: str, inicio: datetime, fin: datetime
) -> str:
    res = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": inicio.isoformat(),
            "ends_at": fin.isoformat(),
            "reason": "Tramite",
        },
    )
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


@pytest.mark.asyncio
async def test_desactivar_un_bloqueo_con_patch_publica_el_rango_liberado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, slot = await _tienda(client, "patch-bloqueo")
    alta = await client.post("/public/waitlist", json=_alta(store, service, slot))
    assert alta.status_code == 201, alta.text
    bloqueo = await _bloquear(client, token, staff, slot, slot + timedelta(hours=1))

    res = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(token),
        json={"is_active": False},
    )
    assert res.status_code == 200, res.text
    assert res.json()["is_active"] is False
    assert await _liberados(test_session) == [
        (slot, slot + timedelta(hours=1), "block_deleted")
    ]

    # Guarda aligned_to_grid: el rango se le avisa al duenio, no se ofrece.
    await process_outbox_batch(test_session)
    assert (await _entrada(test_session, alta.json()["public_id"])).status == "waiting"
    avisos = (
        (
            await test_session.execute(
                select(Notification).where(
                    Notification.type == "waitlist.slot_released"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(avisos) == 1

    # Borrarlo despues no vuelve a liberar lo que ya estaba libre.
    borrado = await client.delete(
        f"/appointment-blocks/{bloqueo}", headers=auth_headers(token)
    )
    assert borrado.status_code == 204, borrado.text
    assert len(await _liberados(test_session)) == 1


@pytest.mark.asyncio
async def test_achicar_o_mover_un_bloqueo_publica_solo_el_tramo_liberado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _store, token, _service, staff, slot = await _tienda(client, "achicar-bloqueo")
    bloqueo = await _bloquear(client, token, staff, slot, slot + timedelta(hours=2))

    # 13:00-15:00 -> 13:30-14:00: quedan libres 13:00-13:30 y 14:00-15:00.
    achicado = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(token),
        json={
            "starts_at": (slot + timedelta(minutes=30)).isoformat(),
            "ends_at": (slot + timedelta(hours=1)).isoformat(),
        },
    )
    assert achicado.status_code == 200, achicado.text
    assert await _liberados(test_session) == [
        (slot, slot + timedelta(minutes=30), "block_deleted"),
        (slot + timedelta(hours=1), slot + timedelta(hours=2), "block_deleted"),
    ]

    # Agrandarlo no libera nada.
    agrandado = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(token),
        json={"ends_at": (slot + timedelta(hours=3)).isoformat()},
    )
    assert agrandado.status_code == 200, agrandado.text
    assert len(await _liberados(test_session)) == 2

    # Moverlo a otro dia libera el rango viejo entero.
    otro_dia = slot + timedelta(days=1)
    movido = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(token),
        json={
            "starts_at": otro_dia.isoformat(),
            "ends_at": (otro_dia + timedelta(hours=1)).isoformat(),
        },
    )
    assert movido.status_code == 200, movido.text
    liberados = await _liberados(test_session)
    assert liberados[-1] == (
        slot + timedelta(minutes=30),
        slot + timedelta(hours=3),
        "block_deleted",
    )

    # Reactivar un bloqueo inactivo tampoco libera nada.
    apagado = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(token),
        json={"is_active": False},
    )
    assert apagado.status_code == 200, apagado.text
    cuantos = len(await _liberados(test_session))
    prendido = await client.patch(
        f"/appointment-blocks/{bloqueo}",
        headers=auth_headers(token),
        json={"is_active": True},
    )
    assert prendido.status_code == 200, prendido.text
    assert len(await _liberados(test_session)) == cuantos
