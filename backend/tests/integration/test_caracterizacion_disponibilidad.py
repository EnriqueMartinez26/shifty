"""Caracterizacion de ``get_available_slots`` antes de partirla (B1-12).

Audit B1-12 (2026-09-19), regla 29 de CLAUDE.md: 250 lineas. Antes de
partirla estos tests fijan la salida completa tal como es HOY para una agenda
con todo junto: turno con buffer, bloqueo con motivo (oculto en el portal),
ventana de antelacion, un profesional sin horario ese dia, grilla completa
(``force_all``) y filtrada, y el cache (la segunda lectura sale igual). La
hora se congela para que la antelacion sea determinista.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient

import core.utils
import modules.notifications.tasks as tasks
from core.utils import local_to_utc
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon


def _local(dia: date, hhmm: str) -> datetime:
    hora, minuto = (int(p) for p in hhmm.split(":"))
    return local_to_utc(dia, time(hora, minuto))


async def _agenda(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str, str, str, date]:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token = await register_and_login(
        client, slug="carac-dispo", email="carac-dispo@example.com"
    )
    ajuste = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"buffer_minutes": 15}
    )
    assert ajuste.status_code == 200, ajuste.text
    service = await create_service(client, token)  # 30 minutos
    con_horario = await create_staff(client, token, service, email="a@carac.com")
    sin_horario = await create_staff(client, token, service, email="b@carac.com")
    dia = (datetime.now(timezone.utc) + timedelta(days=5)).date()
    horario = await client.post(
        f"/staff/{con_horario}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia.weekday(),
            "start_time": "09:00:00",
            "end_time": "12:00:00",
        },
    )
    assert horario.status_code == 200, horario.text
    turno = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service,
            "staff_id": con_horario,
            "starts_at": _local(dia, "10:30").isoformat(),
            "idempotency_key": "carac-dispo-turno-01",
        },
    )
    assert turno.status_code == 201, turno.text
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": con_horario,
            "starts_at": _local(dia, "11:30").isoformat(),
            "ends_at": _local(dia, "12:00").isoformat(),
            "reason": "Tramite",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    assert sin_horario
    return store, token, service, con_horario, dia


def _congelar(monkeypatch: pytest.MonkeyPatch, dia: date) -> None:
    # Antelacion por defecto: 2 h. "Ahora" = 07:15 local -> se vende desde 09:15.
    congelado = _local(dia, "07:15")
    monkeypatch.setattr(core.utils, "now_utc", lambda: congelado)


def _resumen(slots: list[dict[str, Any]]) -> list[tuple[str, str, str, Any]]:
    return [(s["start_time"], s["end_time"], s["status"], s["reason"]) for s in slots]


GRILLA_COMPLETA_PUBLICA = [
    ("09:00:00", "09:30:00", "blocked", "Requiere 2h de antelación"),
    ("09:15:00", "09:45:00", "available", None),
    ("09:30:00", "10:00:00", "available", None),
    ("09:45:00", "10:15:00", "available", None),
    ("10:00:00", "10:30:00", "booked", None),
    ("10:15:00", "10:45:00", "booked", None),
    ("10:30:00", "11:00:00", "booked", None),
    ("10:45:00", "11:15:00", "booked", None),
    ("11:00:00", "11:30:00", "booked", None),
    ("11:15:00", "11:45:00", "blocked", "No disponible"),
    ("11:30:00", "12:00:00", "blocked", "No disponible"),
]


@pytest.mark.asyncio
async def test_grilla_completa_del_portal(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _token, service, staff, dia = await _agenda(client, monkeypatch)
    _congelar(monkeypatch, dia)

    res = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": dia.isoformat(),
            "force_all": "true",
        },
    )

    assert res.status_code == 200, res.text
    slots = res.json()
    assert _resumen(slots) == GRILLA_COMPLETA_PUBLICA
    assert {s["staff_id"] for s in slots} == {staff}
    assert {s["staff_name"] for s in slots} == {"Pro Demo"}
    assert slots[1]["starts_at"] == _local(dia, "09:15").isoformat()
    assert slots[1]["ends_at"] == _local(dia, "09:45").isoformat()


@pytest.mark.asyncio
async def test_grilla_filtrada_del_portal_y_cache(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _token, service, _staff, dia = await _agenda(client, monkeypatch)
    _congelar(monkeypatch, dia)
    params = {
        "store_public_id": store,
        "service_id": service,
        "date": dia.isoformat(),
    }

    primera = await client.get("/public/availability", params=params)
    segunda = await client.get("/public/availability", params=params)

    assert primera.status_code == 200, primera.text
    # El filtro de huecos saca 09:30 (dejaria 15 minutos sueltos antes); lo
    # ocupado y lo bloqueado se muestra igual.
    assert _resumen(primera.json()) == [
        fila for fila in GRILLA_COMPLETA_PUBLICA if fila[0] != "09:30:00"
    ]
    assert segunda.json() == primera.json()


@pytest.mark.asyncio
async def test_panel_ve_el_motivo_del_bloqueo(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store, token, service, _staff, dia = await _agenda(client, monkeypatch)
    _congelar(monkeypatch, dia)

    res = await client.get(
        "/appointments/availability",
        headers=auth_headers(token),
        params={"service_id": service, "date": dia.isoformat()},
    )

    assert res.status_code == 200, res.text
    assert [(s[0], s[2], s[3]) for s in _resumen(res.json())][-2:] == [
        ("11:15:00", "blocked", "Tramite"),
        ("11:30:00", "blocked", "Tramite"),
    ]


@pytest.mark.asyncio
async def test_servicio_inexistente_o_sin_profesionales(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, token, _service, _staff, dia = await _agenda(client, monkeypatch)
    solo = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": "Sin nadie", "duration_minutes": 30, "price": 1},
    )
    assert solo.status_code == 201, solo.text

    for servicio in (solo.json()["public_id"], "01J00000000000000000000000"):
        res = await client.get(
            "/public/availability",
            params={
                "store_public_id": store,
                "service_id": servicio,
                "date": dia.isoformat(),
            },
        )
        assert res.status_code == 200, res.text
        assert res.json() == []
