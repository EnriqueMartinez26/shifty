"""Un bloqueo tiene tope de duracion y uno largo invalida por generacion.

Auditoria 2, AUD2-B1-10 (2026-09-20). Sintoma: nada limitaba cuanto podia
durar un bloqueo (solo `starts_at < ends_at`) y la invalidacion del cache
recorria el rango DIA POR DIA con un `INCR` + `EXPIRE` por cada uno. Un
bloqueo de 2026 a 2036 eran ~3650 dias; con `max_occurrences = 120` rangos
recurrentes, una sola peticion disparaba del orden de 10^5 comandos a Redis,
con la transaccion ya commiteada y el request colgado. Lo podia hacer
cualquier usuario con rol STAFF, sobre el mismo Redis que sostiene el rate
limit y la idempotencia de cobros.

Dos guardas: un rango no puede durar mas de `MAX_BLOCK_DURATION` (regla 9
aplicada a una duracion: cota de los dos lados) en el alta simple, el lote,
el cierre de tienda, el preview y el PATCH, con 422 y sin persistir nada; y
cuando los rangos de una operacion tocan mas de
`MAX_DAYS_INVALIDATED_ONE_BY_ONE` dias, la invalidacion es UN solo `INCR` de
la generacion de la tienda (`invalidate_store_availability`, que ya existia)
en vez de uno por dia.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import ensure_utc_aware
from modules.appointment_blocks.schemas import MAX_BLOCK_DURATION
from modules.appointment_blocks.service import MAX_DAYS_INVALIDATED_ONE_BY_ONE
from modules.staff.model import StaffBlock
from tests.integration.test_caracterizacion_alta_publica import _redis
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_lista_de_espera import _tienda

DIEZ_ANIOS = timedelta(days=3650)


def _rango(inicio: datetime, duracion: timedelta) -> dict[str, str]:
    return {"starts_at": inicio.isoformat(), "ends_at": (inicio + duracion).isoformat()}


async def _bloqueos(session: AsyncSession) -> list[StaffBlock]:
    session.expire_all()
    return list((await session.execute(select(StaffBlock))).scalars())


def _espiar_incr(redis: Any, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Claves que reciben `INCR` (versiones por dia o generacion de la tienda)."""
    claves: list[str] = []
    incr_original = redis.incr

    async def incr(key: str) -> int:
        if key.startswith("availability:"):
            claves.append(key)
        return int(await incr_original(key))

    monkeypatch.setattr(redis, "incr", incr)
    return claves


@pytest.mark.asyncio
async def test_un_bloqueo_de_diez_anios_se_rechaza_en_todos_los_caminos(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _store, token, _service, staff, slot = await _tienda(client, "tope-bloqueo")
    cabeceras = auth_headers(token)
    corto = await client.post(
        "/appointment-blocks/",
        headers=cabeceras,
        json={
            "staff_id": staff,
            **_rango(slot, timedelta(hours=1)),
            "reason": "Tramite",
        },
    )
    assert corto.status_code == 201, corto.text
    largo = _rango(slot + timedelta(days=1), DIEZ_ANIOS)

    alta = await client.post(
        "/appointment-blocks/", headers=cabeceras, json={"staff_id": staff, **largo}
    )
    cierre = await client.post(
        "/appointment-blocks/store-wide", headers=cabeceras, json=largo
    )
    lote = await client.post(
        "/appointment-blocks/batch",
        headers=cabeceras,
        json={"staff_id": staff, "recurrence": "none", **largo},
    )
    preview = await client.post(
        "/appointment-blocks/preview",
        headers=cabeceras,
        json={"staff_id": staff, **largo},
    )
    # El PATCH decide sobre el rango que DEJARIA, aunque venga un solo extremo.
    patch = await client.patch(
        f"/appointment-blocks/{corto.json()['public_id']}",
        headers=cabeceras,
        json={"ends_at": (slot + DIEZ_ANIOS).isoformat()},
    )

    for nombre, res in (
        ("alta", alta),
        ("cierre", cierre),
        ("lote", lote),
        ("preview", preview),
        ("patch", patch),
    ):
        assert res.status_code == 422, (nombre, res.text)
        assert res.json()["error_code"] == "VALIDATION_ERROR", (nombre, res.text)
    filas = await _bloqueos(test_session)
    assert [ensure_utc_aware(b.end_time) for b in filas] == [slot + timedelta(hours=1)]


@pytest.mark.asyncio
async def test_un_bloqueo_de_un_anio_entero_sigue_entrando(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El tope es un tope, no una molestia: vacaciones o licencia larga entran."""
    _store, token, _service, staff, slot = await _tienda(client, "tope-bloqueo-ok")

    res = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            **_rango(slot, MAX_BLOCK_DURATION),
            "reason": "Licencia",
        },
    )

    assert res.status_code == 201, res.text
    assert len(await _bloqueos(test_session)) == 1


@pytest.mark.asyncio
async def test_un_bloqueo_largo_invalida_la_tienda_con_un_solo_incr(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store, token, _service, staff, slot = await _tienda(client, "tope-bloqueo-gen")
    claves = _espiar_incr(await _redis(), monkeypatch)
    dias = MAX_DAYS_INVALIDATED_ONE_BY_ONE + 30

    res = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            **_rango(slot, timedelta(days=dias)),
            "reason": "Obra",
        },
    )

    assert res.status_code == 201, res.text
    # Un solo INCR, y es el de la generacion de la tienda: sin esto eran
    # `dias` INCR + EXPIRE de versiones por dia, con el request colgado.
    assert len(claves) == 1, claves
    assert claves[0].startswith("availability:g:"), claves


@pytest.mark.asyncio
async def test_un_bloqueo_corto_sigue_invalidando_dia_por_dia(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda viva del otro lado: un bloqueo comun no tira la cache de la tienda."""
    _store, token, _service, staff, slot = await _tienda(client, "tope-bloqueo-dia")
    claves = _espiar_incr(await _redis(), monkeypatch)

    res = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={"staff_id": staff, **_rango(slot, timedelta(days=2)), "reason": "Curso"},
    )

    assert res.status_code == 201, res.text
    assert claves, "el bloqueo no invalido nada"
    assert all(c.startswith("availability:v:") for c in claves), claves
    assert len(set(claves)) >= 3, claves  # tres dias locales tocados
