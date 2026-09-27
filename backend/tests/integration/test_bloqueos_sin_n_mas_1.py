"""Crear bloqueos no consulta por turno afectado ni por bloqueo creado.

Audit B1-14 (2026-09-18), regla 12 de CLAUDE.md. Sintoma: ``_classify`` hacia
una consulta de pago POR turno afectado y ``create_blocks`` un ``refresh``
(un SELECT) POR bloqueo creado. Un cierre de dos semanas con cinco
profesionales son hasta 600 bloqueos: 600 SELECT secuenciales, mas uno por
turno adentro, todo con los ``FOR UPDATE`` de los profesionales tomados.

Ahora los pagos de todos los afectados salen de una sola consulta con
``in_()`` y los bloqueos no se refrescan (id y columnas se asignan del lado
de Python en el flush; la sesion no expira al commitear). La clasificacion
"sena acreditada -> no se cancela sola" se conserva identica.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.payments.model import Payment, PaymentStatus
from modules.staff.model import StaffBlock
from tests.integration.test_bloqueos_sobre_turnos import _tienda_con_turnos
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)


def _espiar(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[str], list[object]]:
    """Registra lecturas de ``payments`` y cada ``refresh`` de la sesion."""
    lecturas: list[str] = []
    refrescados: list[object] = []
    execute_original = session.execute
    refresh_original = session.refresh

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        obtener_froms = getattr(statement, "get_final_froms", None)
        tablas = (
            {getattr(f, "name", None) for f in obtener_froms()}
            if obtener_froms
            else set()
        )
        if "payments" in tablas:
            lecturas.append("leer_pagos")
        return await execute_original(statement, *args, **kwargs)

    async def refresh_espiado(instance: object, *args: Any, **kwargs: Any) -> None:
        refrescados.append(instance)
        await refresh_original(instance, *args, **kwargs)

    monkeypatch.setattr(session, "execute", execute_espiado)
    monkeypatch.setattr(session, "refresh", refresh_espiado)
    return lecturas, refrescados


@pytest.mark.asyncio
async def test_bloqueo_recurrente_sobre_varios_turnos_consulta_en_lote(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store, token, _service, staff, turnos, base = await _tienda_con_turnos(
        client, "lote-bloq", cantidad=3
    )
    # El turno del medio tiene la sena acreditada: no se cancela solo.
    con_sena = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == turnos[1])
        )
    ).scalar_one()
    test_session.add(
        Payment(
            store_id=con_sena.store_id,
            appointment_id=con_sena.id,
            amount=Decimal("2500.00"),
            status=PaymentStatus.APPROVED.value,
        )
    )
    await test_session.commit()

    lecturas, refrescados = _espiar(test_session, monkeypatch)
    res = await client.post(
        "/appointment-blocks/batch",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": base.isoformat(),
            "ends_at": (base + timedelta(hours=3)).isoformat(),
            "reason": "Capacitacion",
            "recurrence": "daily",
            "recurrence_until": (base + timedelta(days=3)).isoformat(),
            "max_occurrences": 4,
            "cancel_affected": True,
        },
    )

    assert res.status_code == 201, res.text
    cuerpo = res.json()
    assert cuerpo["created"] == 4
    assert all(b["public_id"] and b["is_active"] for b in cuerpo["blocks"]), cuerpo
    assert all(b["staff_id"] == staff for b in cuerpo["blocks"]), cuerpo
    # Regla 12: una lectura de pagos para los tres afectados, no una por turno.
    assert lecturas.count("leer_pagos") == 1, lecturas
    # Y ningun SELECT por bloqueo creado.
    assert not [r for r in refrescados if isinstance(r, StaffBlock)], refrescados

    # La clasificacion no cambio: el de sena acreditada sigue activo.
    estados = {
        t.id: t.status
        for t in (
            await test_session.execute(
                select(Appointment).where(Appointment.id.in_(turnos))
            )
        ).scalars()
    }
    assert estados[turnos[0]] == "cancelled", estados
    assert estados[turnos[1]] != "cancelled", estados
    assert estados[turnos[2]] == "cancelled", estados


@pytest.mark.asyncio
async def test_la_respuesta_del_alta_devuelve_el_rango_en_utc(
    client: AsyncClient,
) -> None:
    """B1-14, revision 2026-09-18: sin el ``refresh`` la respuesta repetia el
    offset que mando el cliente (o salia sin zona) en vez de UTC."""
    from datetime import datetime, timezone

    from core.utils import ARGENTINA_TZ

    _store, token, _service, staff, _turnos, base = await _tienda_con_turnos(
        client, "bloq-utc", cantidad=0
    )
    inicio_local = (base + timedelta(days=1)).astimezone(ARGENTINA_TZ)
    fin_local = inicio_local + timedelta(hours=1)
    assert inicio_local.isoformat().endswith("-03:00")

    res = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": inicio_local.isoformat(),
            "ends_at": fin_local.isoformat(),
            "reason": "Tramite",
        },
    )

    assert res.status_code == 201, res.text
    inicio = datetime.fromisoformat(res.json()["starts_at"])
    fin = datetime.fromisoformat(res.json()["ends_at"])
    assert inicio.utcoffset() == timedelta(0), res.json()
    assert fin.utcoffset() == timedelta(0), res.json()
    assert inicio == inicio_local.astimezone(timezone.utc)
    assert fin == fin_local.astimezone(timezone.utc)
