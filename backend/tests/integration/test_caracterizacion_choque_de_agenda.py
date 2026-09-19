"""Caracterizacion de "este rango choca con la agenda del profesional" (S-07).

Seguimiento S-07 (2026-09-19). El panel (``_lock_and_validate_slot``) y el
portal (``staff_can_take_range`` / ``_lock_and_recheck``) resolvian con dos
implementaciones propias la misma pregunta: lock del profesional, bloqueo
activo que solapa y turno activo que choca (ensanchado por el buffer,
excluyendo el turno que se mueve). Antes de unificar el nucleo estos tests
fijan lo que cada camino responde HOY, incluidas sus diferencias de
presentacion (el panel sugiere horario y detalla; el portal no), la
precedencia del bloqueo sobre el choque, el buffer y la exclusion del turno
propio. Pasan antes y despues de la unificacion sin cambiar una asercion.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

import modules.notifications.tasks as tasks
from core.config import settings
from core.utils import ensure_utc_aware
from tests.integration.test_caracterizacion_alta_publica import (
    _reserva,
    _Tienda,
    _tienda,
)
from tests.integration.test_caracterizacion_autogestion import TELEFONO, _verificar
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_mails_al_cliente import Buzon


async def _preparar(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, slug: str
) -> tuple[_Tienda, str]:
    """Turno del cliente a las 10:00 local, otro turno a las 12:00 (buffer de
    15 minutos) y un bloqueo de 14:00 a 15:00."""
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    t = await _tienda(client, slug)
    ajuste = await client.patch(
        "/stores/me", headers=auth_headers(t.token), json={"buffer_minutes": 15}
    )
    assert ajuste.status_code == 200, ajuste.text
    propio = await client.post("/public/appointments", json=_reserva(t, f"{slug}-1"))
    assert propio.status_code == 201, propio.text
    ajeno = await client.post(
        "/public/appointments",
        json=_reserva(
            t,
            f"{slug}-2",
            starts_at=(t.slot + timedelta(hours=2)).isoformat(),
            client_phone="+5491155559201",
            client_email=f"ajeno-{slug}@example.com",
        ),
    )
    assert ajeno.status_code == 201, ajeno.text
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(t.token),
        json={
            "staff_id": t.staff,
            "starts_at": (t.slot + timedelta(hours=2)).isoformat(),
            "ends_at": (t.slot + timedelta(hours=3)).isoformat(),
            "reason": "Tramite",
            "cancel_affected": False,
        },
    )
    # El bloqueo cae sobre un turno: sin cancel_affected el alta responde 409.
    assert bloqueo.status_code == 409, bloqueo.text
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(t.token),
        json={
            "staff_id": t.staff,
            "starts_at": (t.slot + timedelta(hours=4)).isoformat(),
            "ends_at": (t.slot + timedelta(hours=5)).isoformat(),
            "reason": "Tramite",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    await _verificar(client, t)
    return t, str(propio.json()["public_id"])


async def _portal(client: AsyncClient, turno: str, inicio: datetime, clave: str) -> Any:
    return await client.patch(
        f"/public/client/appointments/{turno}/reschedule",
        json={
            "phone": TELEFONO,
            "new_starts_at": inicio.isoformat(),
            "idempotency_key": clave,
        },
    )


async def _panel(
    client: AsyncClient, t: _Tienda, turno: str, inicio: datetime, clave: str
) -> Any:
    return await client.patch(
        f"/appointments/{turno}/reschedule",
        headers=auth_headers(t.token),
        json={"new_starts_at": inicio.isoformat(), "idempotency_key": clave},
    )


def _hora(valor: str | None) -> datetime | None:
    return ensure_utc_aware(datetime.fromisoformat(valor)) if valor else None


@pytest.mark.asyncio
async def test_choques_del_portal(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _preparar(client, monkeypatch, "choque-portal")

    bloqueado = await _portal(
        client, turno, t.slot + timedelta(hours=4), "choque-cp-bl-01"
    )
    ocupado = await _portal(
        client, turno, t.slot + timedelta(hours=2), "choque-cp-oc-01"
    )
    # 12:40 local: no pisa el turno de 12:00-12:30, pero queda a 10 min (buffer 15).
    pegado = await _portal(
        client, turno, t.slot + timedelta(hours=2, minutes=40), "choque-cp-bf-01"
    )

    assert bloqueado.status_code == 409, bloqueado.text
    assert (bloqueado.json()["error_code"], bloqueado.json()["message"]) == (
        "SCHEDULE_BLOCKED",
        "Ese horario esta bloqueado en la agenda",
    )
    for res in (ocupado, pegado):
        assert res.status_code == 409, res.text
        assert (res.json()["error_code"], res.json()["message"]) == (
            "APPOINTMENT_CONFLICT",
            "El horario solicitado ya no está disponible.",
        )
        assert res.json()["detail"] == {
            "conflict_start": None,
            "conflict_end": None,
            "suggestion": None,
        }
    # El turno propio no choca consigo mismo (se excluye).
    mismo = await _portal(
        client, turno, t.slot + timedelta(minutes=15), "choque-cp-ok-01"
    )
    assert mismo.status_code == 200, mismo.text


@pytest.mark.asyncio
async def test_choques_del_panel(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, turno = await _preparar(client, monkeypatch, "choque-panel")

    bloqueado = await _panel(
        client, t, turno, t.slot + timedelta(hours=4), "choque-pp-bl-01"
    )
    ocupado = await _panel(
        client, t, turno, t.slot + timedelta(hours=2), "choque-pp-oc-01"
    )
    pegado = await _panel(
        client, t, turno, t.slot + timedelta(hours=2, minutes=40), "choque-pp-bf-01"
    )

    assert bloqueado.status_code == 409, bloqueado.text
    assert bloqueado.json()["error_code"] == "SCHEDULE_BLOCKED"
    detalle = bloqueado.json()["detail"]
    assert detalle["reason"] == "Tramite"
    assert _hora(detalle["block_start"]) == t.slot + timedelta(hours=4)
    assert _hora(detalle["block_end"]) == t.slot + timedelta(hours=5)
    assert _hora(detalle["suggestion"]) == t.slot + timedelta(hours=5)
    for res in (ocupado, pegado):
        assert res.status_code == 409, res.text
        assert res.json()["error_code"] == "APPOINTMENT_CONFLICT"
        detalle = res.json()["detail"]
        assert _hora(detalle["conflict_start"]) == t.slot + timedelta(hours=2)
        assert _hora(detalle["conflict_end"]) == t.slot + timedelta(hours=2.5)
        # Primer hueco despues del turno + buffer.
        assert _hora(detalle["suggestion"]) == t.slot + timedelta(hours=2.75)
    mismo = await _panel(
        client, t, turno, t.slot + timedelta(minutes=15), "choque-pp-ok-01"
    )
    assert mismo.status_code == 200, mismo.text


@pytest.mark.asyncio
async def test_el_bloqueo_gana_sobre_el_choque_en_los_dos_caminos(
    client: AsyncClient, test_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rango con bloqueo Y turno a la vez: los dos responden SCHEDULE_BLOCKED."""
    from sqlalchemy import update

    from modules.staff.model import StaffBlock

    t, turno = await _preparar(client, monkeypatch, "choque-ambos")
    # Se fuerza un bloqueo sobre el turno ajeno de 12:00 (el alta lo rechaza).
    await test_session.execute(
        update(StaffBlock).values(
            start_time=t.slot + timedelta(hours=2),
            end_time=t.slot + timedelta(hours=3),
        )
    )
    await test_session.commit()

    portal = await _portal(client, turno, t.slot + timedelta(hours=2), "choque-ca-p-01")
    panel = await _panel(
        client, t, turno, t.slot + timedelta(hours=2), "choque-ca-a-01"
    )

    assert (portal.status_code, portal.json()["error_code"]) == (
        409,
        "SCHEDULE_BLOCKED",
    )
    assert (panel.status_code, panel.json()["error_code"]) == (409, "SCHEDULE_BLOCKED")
    # El panel busca la sugerencia desde el fin del turno que choca.
    assert _hora(panel.json()["detail"]["suggestion"]) == t.slot + timedelta(hours=3)
