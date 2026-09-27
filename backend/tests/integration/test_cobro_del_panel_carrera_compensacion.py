"""La compensacion del link del panel nunca borra un cobro de otra request.

2026-09-19, S-17: ``test_pg_rafaga_cobros.py::test_rafaga_de_links_de_pago_
del_mismo_turno_deja_un_solo_cobro`` fallaba 1 de cada 3 corridas con CERO
cobros para el turno. Carrera real en ``create_panel_payment_preference``:

1. La request D leia "no hay cobro" (``ya_existia = False``) con un SELECT
   propio.
2. Antes de su fase 1, la request A insertaba el cobro y commiteaba; la fase
   1 de D lo encontraba y no insertaba nada.
3. La fase 2 de D chocaba con la de A sobre la version del cobro
   (StaleDataError -> 409) y, como D "no lo habia visto", lo compensaba
   BORRANDOLO: el cobro de A desaparecia y A ya habia respondido 200.

Aca se fuerza ese orden de forma determinista: el cobro ya existe (lo creo
"A"), el SELECT previo de D se hace ciego a el y la fase 2 de D levanta
StaleDataError. El cobro tiene que sobrevivir.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.sql import Select

import modules.payments.service as payments_service
from modules.payments.model import Payment, PaymentStatus
from tests.integration.test_cobro_del_panel_dos_fases import _turno_con_cobro_online
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


def _select_previo_ciego(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    """El primer ``SELECT payments.id`` no ve el cobro: simula que A commiteo
    justo despues de esa lectura de D."""
    ejecutar = session.execute
    usado: list[bool] = []

    async def execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
        if (
            not usado
            and isinstance(statement, Select)
            and [c.key for c in statement.selected_columns] == ["id"]
            and statement.get_final_froms()
            and getattr(statement.get_final_froms()[0], "name", "") == "payments"
        ):
            usado.append(True)
            return await ejecutar(select(Payment.id).where(false()), *args, **kwargs)
        return await ejecutar(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", execute)


def _fase_2_en_conflicto(monkeypatch: pytest.MonkeyPatch) -> None:
    async def conflicto(*args: Any, **kwargs: Any) -> None:
        raise StaleDataError("otra request sello el cobro primero")

    monkeypatch.setattr(payments_service, "_attach_provider_link", conflicto)


@pytest.mark.asyncio
async def test_un_conflicto_en_la_fase_2_no_borra_el_cobro_que_creo_otra_request(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store, token = await register_and_login(
        client, slug="s17-ajeno", email="s17-ajeno@test.com"
    )
    _servicio, turno = await _turno_con_cobro_online(client, token, "s17-ajeno")
    store_id = cast(
        str, (await client.get("/me", headers=auth_headers(token))).json()["store_id"]
    )
    # La fase 1 de "A": cobro PENDING con link placeholder, ya commiteado.
    test_session.add(
        Payment(
            store_id=store_id,
            appointment_id=turno,
            amount=Decimal("3000.00"),
            status=PaymentStatus.PENDING.value,
            preference_id=f"pref_{turno}",
            payment_link=f"https://payments.shifty.local/pay/{turno}",
        )
    )
    await test_session.commit()

    _select_previo_ciego(monkeypatch, test_session)
    _fase_2_en_conflicto(monkeypatch)

    respuesta = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(token)
    )
    assert respuesta.status_code == 409, respuesta.text

    await test_session.rollback()
    cobros = (
        (
            await test_session.execute(
                select(Payment).where(Payment.appointment_id == turno)
            )
        )
        .scalars()
        .all()
    )
    assert len(cobros) == 1, "la compensacion borro un cobro que no era suyo"


@pytest.mark.asyncio
async def test_un_conflicto_no_compensa_ni_siquiera_el_cobro_propio(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la fase 2 choca con otra request, esa otra esta sellando el cobro:
    borrarlo le dejaria un 200 apuntando a una fila inexistente."""
    _store, token = await register_and_login(
        client, slug="s17-propio", email="s17-propio@test.com"
    )
    _servicio, turno = await _turno_con_cobro_online(client, token, "s17-propio")
    _fase_2_en_conflicto(monkeypatch)

    respuesta = await client.post(
        f"/payments/preferences/{turno}", headers=auth_headers(token)
    )
    assert respuesta.status_code == 409, respuesta.text

    await test_session.rollback()
    cobros = (
        (
            await test_session.execute(
                select(Payment).where(Payment.appointment_id == turno)
            )
        )
        .scalars()
        .all()
    )
    assert len(cobros) == 1
