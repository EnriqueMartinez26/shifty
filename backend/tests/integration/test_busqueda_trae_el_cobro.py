"""La busqueda de turnos trae el precio congelado y el cobro de cada turno.

2026-10-08, QA en el celular (decision de Mateo): "Confirmar pago" en Cobros
registraba al instante, sin pedir importe, y despues de pagar la tarjeta seguia
igual (CONFIRMADO con el mismo boton). La pantalla no podia hacer otra cosa:
``/appointments/search`` no traia el precio del turno ni su cobro, asi que no
habia con que precargar el importe ni con que mostrar lo pagado.

Ahora cada resultado trae ``price_amount`` (el snapshot del turno),
``payment_status`` y ``payment_amount`` (el cobro del turno, a lo sumo uno por
``uq_payments_store_appointment``). Es aditivo: los campos viejos no cambian,
y el cobro entra por un LEFT JOIN en la MISMA consulta de la pagina (regla 12:
ninguna consulta mas por turno ni por pagina), filtrado por ``store_id``
(defensa en profundidad junto a la RLS, CLAUDE.md §2).

Los campos del cobro los ve quien opera cobros (``_require_payment_manager``:
administracion y profesional). La recepcion busca turnos pero no opera cobros
(ni el router de pagos ni la ruta de Cobros la dejan): para ella vienen en
``None``, como el telefono del cliente para quien no administra.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from core.security import hash_password
from modules.appointments.model import AppointmentStatus
from modules.payments.model import PaymentStatus
from modules.users.model import User, UserRole
from tests.integration.test_busqueda_y_resumen_contrato_aditivo import (
    _de_turnos,
    _Registro,
)
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_reportes_funciones_cortas import _Semilla, _tienda


async def _sembrar(
    client: AsyncClient, test_session: AsyncSession
) -> tuple[str, dict[str, str], str]:
    token, store, staff, corto = await _tienda(client, test_session, "cobro-busq")
    semilla = _Semilla(test_session, store, staff)
    ana = semilla.cliente("Ana", "Cobro")
    await test_session.commit()
    casos = {
        "sin_cobro": (time(9, 0), AppointmentStatus.COMPLETED, None),
        "sena_viva": (
            time(10, 0),
            AppointmentStatus.PENDING_PAYMENT,
            (Decimal("960"), PaymentStatus.PENDING),
        ),
        "sena_pagada": (
            time(11, 0),
            AppointmentStatus.CONFIRMED,
            (Decimal("960"), PaymentStatus.APPROVED),
        ),
    }
    ids = {}
    for clave, (hora, estado, pago) in casos.items():
        ids[clave] = await semilla.turno(
            f"cobro-{clave}",
            date(2026, 10, 8),
            hora,
            corto,
            ana,
            estado,
            precio=Decimal("3200"),
            pago=pago,
        )
    return token, ids, store.id


@pytest.mark.asyncio
async def test_la_busqueda_trae_precio_y_cobro_de_cada_turno(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """2026-10-08: sin precio ni cobro, Cobros no podia precargar el importe ni
    mostrar lo pagado."""
    token, ids, _ = await _sembrar(client, test_session)
    res = await client.get(
        "/appointments/search",
        params={"page": 1, "page_size": 10},
        headers=auth_headers(token),
    )
    assert res.status_code == 200, res.text
    por_id = {r["public_id"]: r for r in res.json()["results"]}

    sin_cobro = por_id[ids["sin_cobro"]]
    assert Decimal(sin_cobro["price_amount"]) == Decimal("3200")
    assert sin_cobro["payment_status"] is None
    assert sin_cobro["payment_amount"] is None

    viva = por_id[ids["sena_viva"]]
    assert viva["payment_status"] == PaymentStatus.PENDING.value
    assert Decimal(viva["payment_amount"]) == Decimal("960")

    pagada = por_id[ids["sena_pagada"]]
    assert pagada["payment_status"] == PaymentStatus.APPROVED.value
    assert Decimal(pagada["payment_amount"]) == Decimal("960")
    assert Decimal(pagada["price_amount"]) == Decimal("3200")


@pytest.mark.asyncio
async def test_el_cobro_entra_en_la_misma_consulta_de_la_pagina(
    client: AsyncClient, test_session: AsyncSession, test_engine: AsyncEngine
) -> None:
    """2026-10-08: el cobro no suma consultas (regla 12) y su join lleva
    ``store_id`` (CLAUDE.md §2)."""
    token, _, _ = await _sembrar(client, test_session)
    with _Registro(test_engine) as sentencias:
        res = await client.get(
            "/appointments/search",
            params={"page": 1, "page_size": 10},
            headers=auth_headers(token),
        )
    assert res.status_code == 200, res.text
    turnos = _de_turnos(sentencias)
    # Total + pagina, como antes: el cobro no agrega una sentencia.
    assert len(turnos) == 2, turnos
    assert not [s for s in sentencias if "from payments" in s], sentencias
    (pagina,) = [s for s in turnos if "count(" not in s]
    assert "left outer join payments" in pagina, pagina
    assert "payments.store_id" in pagina, pagina


@pytest.mark.asyncio
async def test_la_recepcion_no_ve_el_cobro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """2026-10-08: la recepcion no opera cobros, asi que la busqueda no le
    expone el importe ni el estado del cobro de cada turno."""
    _, ids, store_id = await _sembrar(client, test_session)
    test_session.add(
        User(
            email="recepcion-cobro@test.com",
            hashed_password=hash_password("Password123!"),
            first_name="Recep",
            last_name="Cion",
            role=UserRole.RECEPTIONIST,
            store_id=store_id,
        )
    )
    await test_session.commit()
    login = await client.post(
        "/auth/login",
        json={"email": "recepcion-cobro@test.com", "password": "Password123!"},
    )
    assert login.status_code == 200, login.text
    res = await client.get(
        "/appointments/search",
        params={"page": 1, "page_size": 10},
        headers=auth_headers(login.json()["access_token"]),
    )
    assert res.status_code == 200, res.text
    por_id = {r["public_id"]: r for r in res.json()["results"]}
    pagada = por_id[ids["sena_pagada"]]
    assert pagada["price_amount"] is None
    assert pagada["payment_status"] is None
    assert pagada["payment_amount"] is None
