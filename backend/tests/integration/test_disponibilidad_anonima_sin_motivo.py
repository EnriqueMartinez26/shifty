"""La disponibilidad sin token no publica el motivo privado de un bloqueo.

Auditoria 2, AUD2-B1-04 (2026-09-20). Sintoma: `GET /appointments/availability`
acepta usuario OPCIONAL y, cuando no hay token, resolvia la tienda por el
`service_id` y llamaba al servicio con el default `hide_private_reasons=False`.
El portal (`/public/availability`) si lo pasa en True, asi que el mismo
bloqueo salia "No disponible" por un camino y con el texto crudo del duenio
("Turno medico", "Vacaciones en Brasil") por el otro. El `service_id` esta en
`/public/services`, que es anonimo: alcanzaba con pedirlo.

Regla 20 de CLAUDE.md (errores y datos neutros hacia afuera): a un anonimo se
le dice que el horario no esta disponible, no por que.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

MOTIVO = "Turno medico de Pro Demo"


async def _tienda_con_bloqueo(client: AsyncClient) -> tuple[str, str, str]:
    store, token = await register_and_login(
        client, slug="motivo-privado", email="motivo-privado@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    horario = await client.post(
        f"/staff/{staff}/schedules",
        headers=auth_headers(token),
        json={
            "day_of_week": dia.weekday(),
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    assert horario.status_code == 200, horario.text
    inicio = dia.replace(hour=13, minute=0, second=0, microsecond=0)
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": inicio.isoformat(),
            "ends_at": (inicio + timedelta(hours=1)).isoformat(),
            "reason": MOTIVO,
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    return store, token, service


def _motivos_bloqueados(slots: list[dict[str, object]]) -> list[object]:
    return [s.get("reason") for s in slots if s.get("status") == "blocked"]


@pytest.mark.asyncio
async def test_sin_token_el_motivo_del_bloqueo_no_sale(client: AsyncClient) -> None:
    store, _token, service = await _tienda_con_bloqueo(client)
    dia = (datetime.now(timezone.utc) + timedelta(days=5)).date()

    res = await client.get(
        "/appointments/availability",
        params={"service_id": service, "date": dia.isoformat()},
    )

    assert res.status_code == 200, res.text
    motivos = _motivos_bloqueados(res.json())
    assert motivos, "el bloqueo no aparecio en la grilla"
    assert MOTIVO not in motivos
    assert "No disponible" in motivos
    assert store


@pytest.mark.asyncio
async def test_el_personal_de_la_tienda_lo_sigue_viendo(client: AsyncClient) -> None:
    """El motivo es util para quien administra la agenda: ahi no se oculta."""
    _store, token, service = await _tienda_con_bloqueo(client)
    dia = (datetime.now(timezone.utc) + timedelta(days=5)).date()

    res = await client.get(
        "/appointments/availability",
        headers=auth_headers(token),
        params={"service_id": service, "date": dia.isoformat()},
    )

    assert res.status_code == 200, res.text
    assert MOTIVO in _motivos_bloqueados(res.json())


@pytest.mark.asyncio
async def test_el_portal_y_el_anonimo_dicen_lo_mismo(client: AsyncClient) -> None:
    """Los dos caminos anonimos comparten criterio (y no se pisan en el cache)."""
    store, _token, service = await _tienda_con_bloqueo(client)
    dia = (datetime.now(timezone.utc) + timedelta(days=5)).date()

    portal = await client.get(
        "/public/availability",
        params={
            "store_public_id": store,
            "service_id": service,
            "date": dia.isoformat(),
        },
    )
    panel_sin_token = await client.get(
        "/appointments/availability",
        params={"service_id": service, "date": dia.isoformat()},
    )

    assert (portal.status_code, panel_sin_token.status_code) == (200, 200)
    assert _motivos_bloqueados(portal.json()) == _motivos_bloqueados(
        panel_sin_token.json()
    )
