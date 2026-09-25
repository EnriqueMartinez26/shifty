"""La idempotencia del panel es por tienda, no global.

2026-09-24, revision de perf/f4-back. Sintoma: el auto-turno
(``POST /appointments/`` sin cliente) y la reprogramacion del panel
(``PATCH /appointments/{id}/reschedule``) guardaban la respuesta en Redis bajo
la clave CRUDA que manda el llamador (``idempotency:{key}``). La misma cadena
mandada desde OTRA tienda devolvia la respuesta cacheada de la primera: el
turno ajeno (id, horario, notas). Mismo defecto que AUD2-B1-06 cerro en el
portal. Ahora la clave de Redis lleva la tienda adelante.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _tienda(client: AsyncClient, slug: str) -> tuple[str, str, str, datetime]:
    _store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return (
        token,
        service,
        staff,
        dia.replace(hour=11, minute=0, second=0, microsecond=0),
    )


async def _auto_turno(
    client: AsyncClient,
    token: str,
    service: str,
    staff: str,
    slot: datetime,
    clave: str,
) -> dict[str, str]:
    res = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "notes": f"nota de {token[-6:]}",
            "idempotency_key": clave,
        },
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


@pytest.mark.asyncio
async def test_la_misma_clave_en_dos_tiendas_no_comparte_el_auto_turno(
    client: AsyncClient,
) -> None:
    a = await _tienda(client, "idem-panel-a")
    b = await _tienda(client, "idem-panel-b")

    turno_a = await _auto_turno(client, *a, "clave-compartida-alta")
    # La base exige unico el idempotency_key del turno (ultima defensa): la
    # segunda tienda no puede crear otro con la MISMA clave, pero tampoco
    # puede recibir el turno de la primera.
    res_b = await client.post(
        "/appointments/",
        headers=auth_headers(b[0]),
        json={
            "service_id": b[1],
            "staff_id": b[2],
            "starts_at": b[3].isoformat(),
            "idempotency_key": "clave-compartida-alta",
        },
    )

    assert res_b.status_code == 409, res_b.text
    assert turno_a["public_id"] not in res_b.text
    assert res_b.json()["error_code"] == "RESOURCE_CONFLICT"


@pytest.mark.asyncio
async def test_la_misma_clave_en_dos_tiendas_no_comparte_la_reprogramacion(
    client: AsyncClient,
) -> None:
    a = await _tienda(client, "idem-repro-a")
    b = await _tienda(client, "idem-repro-b")
    turno_a = await _auto_turno(client, *a, "idem-repro-a-alta")
    turno_b = await _auto_turno(client, *b, "idem-repro-b-alta")

    movido_a = await client.patch(
        f"/appointments/{turno_a['public_id']}/reschedule",
        headers=auth_headers(a[0]),
        json={
            "new_starts_at": (a[3] + timedelta(hours=1)).isoformat(),
            "idempotency_key": "clave-compartida-repro",
        },
    )
    movido_b = await client.patch(
        f"/appointments/{turno_b['public_id']}/reschedule",
        headers=auth_headers(b[0]),
        json={
            "new_starts_at": (b[3] + timedelta(hours=2)).isoformat(),
            "idempotency_key": "clave-compartida-repro",
        },
    )

    assert movido_a.status_code == 200, movido_a.text
    # Antes: 200 con el turno de la tienda A. Ahora no ve la respuesta ajena.
    assert movido_a.json()["public_id"] not in movido_b.text
    assert movido_b.status_code == 409, movido_b.text
