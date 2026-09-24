"""El predicado de OTP se resuelve una vez por request (F3-03).

Plan de rendimiento, R1-05 (2026-09-24). La reserva publica pregunta dos
veces lo mismo al ``OtpService`` del request: ``may_book_with_otp`` (gate del
flag ``otp_booking``) y ``is_client_contact_verified`` (historial para la
regla de sena). Cada pregunta volvia a buscar la ficha del telefono y su
verificacion: la ficha se leia TRES veces por reserva.

Ahora la instancia (una por request) recuerda la ficha y el veredicto. Una
escritura de la misma instancia (``request_code`` / ``verify_code``) los
olvida: el memo no puede servir un "no verificado" viejo despues de verificar.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from core.config import settings
from modules.otp.service import OtpService
from modules.stores.model import Store
from tests.integration.test_caracterizacion_autogestion import TELEFONO, _con_turno


@contextmanager
def _sentencias(engine: AsyncEngine) -> Iterator[list[str]]:
    registradas: list[str] = []

    def registrar(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        registradas.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", registrar)
    try:
        yield registradas
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", registrar)


def _sin_despacho(*_args: str) -> None:
    return None


@pytest.mark.asyncio
async def test_el_predicado_se_resuelve_una_vez_y_se_olvida_al_verificar(
    client: AsyncClient,
    test_engine: AsyncEngine,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t, _turno = await _con_turno(client, monkeypatch, "otp-memo", otp=False)
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)
    store_id = await test_session.scalar(
        select(Store.id).where(Store.public_id == t.store)
    )
    assert store_id is not None
    otp = OtpService(test_session)

    with _sentencias(test_engine) as primera:
        assert not await otp.is_client_contact_verified(
            store_id=store_id, phone=TELEFONO
        )
    with _sentencias(test_engine) as repetidas:
        assert not await otp.is_client_contact_verified(
            store_id=store_id, phone=TELEFONO
        )
        assert not await otp.may_book_with_otp(store_id=store_id, phone=TELEFONO)

    # La ficha, la verificacion contra su email y (solo para el motivo del
    # log) si hubo alguna verificacion contra otro buzon.
    assert len(primera) == 3, primera
    assert repetidas == [], "el mismo request no vuelve a preguntar"

    pedido = await otp.request_code(
        store_id=store_id,
        phone=TELEFONO,
        channel="whatsapp",
        schedule_dispatch=_sin_despacho,
    )
    await otp.verify_code(
        store_id=store_id, phone=TELEFONO, code=str(pedido["debug_code"])
    )

    assert await otp.is_client_contact_verified(store_id=store_id, phone=TELEFONO)
    assert await otp.may_book_with_otp(store_id=store_id, phone=TELEFONO)
