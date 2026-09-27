"""Cuanto le cuesta a la base ofrecer un cupo liberado (F3-07).

Plan de rendimiento, R1-07 (2026-09-24). ``offer_released_slot`` corre por
cada ``slot_released`` del outbox y, dentro de ``expire_lapsed_offers``, por
cada oferta vencida del lote (hasta 100) en UNA transaccion con las filas
tomadas. Eran ~10 sentencias por cupo: la tienda y el profesional enteros con
``db.get`` (y sus horarios y servicios en cascada) para leer cuatro columnas
de una y dos del otro, y los servicios del profesional en una consulta aparte
antes de las entradas.

Ahora: cupo libre (turno + bloqueo), oferta viva, entradas que encajan (con
los servicios del profesional en un ``IN`` por subconsulta) y tienda +
profesional en columnas: 5. El mail sale igual.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import modules.notifications.tasks as tasks
from core.config import settings
from modules.stores.model import Store
from modules.waitlist.model import WaitlistEntry
from modules.waitlist.offers import offer_released_slot
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_lista_de_espera import _alta, _reservar, _tienda
from tests.integration.test_lista_de_espera_concurrencia import _slot
from tests.integration.test_mails_al_cliente import Buzon


@pytest.mark.asyncio
async def test_ofrecer_un_cupo_cuesta_cinco_sentencias_y_arma_el_mismo_mail(
    client: AsyncClient,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, slot = await _tienda(client, "espera-sql")
    alta = await client.post("/public/waitlist", json=_alta(store, service, slot))
    assert alta.status_code == 201, alta.text
    pid = await _reservar(client, store, service, staff, slot, "espera-sql-000001")
    cancelar = await client.patch(
        f"/appointments/{pid}/cancel", headers=auth_headers(token)
    )
    assert cancelar.status_code == 200, cancelar.text
    entrada = (await test_session.execute(select(WaitlistEntry))).scalar_one()
    tienda = (
        await test_session.execute(select(Store).where(Store.public_id == store))
    ).scalar_one()
    # El telefono de la tienda sale de theme_config (propiedad, no columna).
    tienda.theme_config = {**(tienda.theme_config or {}), "whatsapp_number": "5491100"}
    await test_session.commit()
    # Como el lote real: la sesion no tiene nada cargado.
    test_session.expunge_all()

    sentencias: list[str] = []

    def registrar(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        sentencias.append(" ".join(statement.split()).lower())

    event.listen(test_engine.sync_engine, "before_cursor_execute", registrar)
    try:
        resultado = await offer_released_slot(
            test_session,
            _slot(entrada.store_id, staff, slot),
            now=datetime.now(timezone.utc),
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", registrar)

    assert resultado.offered_entry_id == entrada.id
    assert resultado.pending_email is not None
    detalles = resultado.pending_email.details
    base = settings.FRONTEND_URL.rstrip("/")
    assert detalles["staff"] == "Pro Demo"
    assert detalles["staff_kind"] == "person"
    assert detalles["store_name"] == tienda.name
    assert detalles["store_phone"] == "5491100"
    assert detalles["booking_url"] == f"{base}/b/{tienda.slug}"
    assert str(detalles["offer_url"]).startswith(
        f"{base}/b/{tienda.slug}?service={service}&staff={staff}&date="
    )
    cascadas = [
        s
        for s in sentencias
        if "store_schedules" in s or "staff_1" in s or "from schedules" in s
    ]
    assert cascadas == [], cascadas
    assert len(sentencias) <= 5, "\n".join(sentencias)
    await test_session.rollback()
