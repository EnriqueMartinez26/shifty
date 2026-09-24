"""Paginacion por clave, aditiva, en la busqueda de turnos y en el fiado.

2026-09-24, plan de rendimiento F3-08 (hallazgo R7-11). La busqueda de turnos
admite ``page`` hasta 10.000 con ``page_size`` 100 (``OFFSET`` hasta ~1 M) y
el historial de fiado ``offset`` hasta 100.000: la base lee y descarta todas
las filas saltadas en cada pagina. Ahora las dos aceptan ``after``, un cursor
opaco con la clave de la ultima fila vista (``(starts_at, id)`` en turnos,
``(created_at, id)`` en el fiado), y devuelven ``next_cursor``; la pagina
siguiente arranca en el indice justo despues de esa clave. ``page``/``offset``
siguen funcionando igual (regla 9, con sus dos cotas).

El recorrido por cursor tiene que dar EXACTAMENTE las mismas filas y en el
mismo orden que el listado por ``OFFSET``, tambien con turnos o movimientos
empatados en el instante (el ``id`` desempata). El plan en Postgres lo fija
``tests/postgres/test_pg_paginacion_por_clave.py``.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.keyset import encode_cursor
from core.security import hash_password
from modules.appointments.model import AppointmentStatus
from modules.ledger.model import CustomerLedger
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_fiado_del_cliente_paginado import (
    _cargar,
    _tienda_con_deudor,
)
from tests.integration.test_reportes_funciones_cortas import _Semilla, _tienda


# Instantes validos en su zona que desbordan al pasarlos a UTC
# (``OverflowError`` en ``astimezone``): antes salian 500 por el handler
# generico, en la busqueda y en el fiado.
DESBORDES = (
    base64.urlsafe_b64encode(b"0001-01-01T00:00:00+14:00|abc").decode(),
    base64.urlsafe_b64encode(b"9999-12-31T23:59:59-23:59|abc").decode(),
)


async def _sembrar_turnos(client: AsyncClient, test_session: AsyncSession) -> str:
    """Siete turnos, tres empatados a la misma hora."""
    token, store, staff, corto = await _tienda(client, test_session, "f308-clave")
    semilla = _Semilla(test_session, store, staff)
    ana = semilla.cliente("Ana", "Clave")
    await test_session.commit()
    horarios = [
        (date(2026, 9, 1), time(10, 0)),
        (date(2026, 9, 2), time(10, 0)),
        (date(2026, 9, 2), time(10, 0)),
        (date(2026, 9, 2), time(10, 0)),
        (date(2026, 9, 3), time(9, 0)),
        (date(2026, 9, 4), time(18, 30)),
        (date(2026, 9, 5), time(12, 0)),
    ]
    for indice, (dia, hora) in enumerate(horarios):
        await semilla.turno(
            f"f308-{indice}", dia, hora, corto, ana,
            AppointmentStatus.CONFIRMED, precio=Decimal("10000"),
        )  # fmt: skip
    return token


async def _buscar(client: AsyncClient, token: str, **params: Any) -> dict[str, Any]:
    res = await client.get(
        "/appointments/search", params=params, headers=auth_headers(token)
    )
    assert res.status_code == 200, res.text
    cuerpo: dict[str, Any] = res.json()
    return cuerpo


@pytest.mark.asyncio
async def test_recorrer_la_busqueda_por_cursor_da_lo_mismo_que_por_offset(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _sembrar_turnos(client, test_session)
    todo = await _buscar(client, token, page_size=100)
    esperado = [r["public_id"] for r in todo["results"]]
    assert len(esperado) == 7 and todo["next_cursor"] is None

    vistos: list[str] = []
    primera = await _buscar(client, token, page_size=2)
    assert primera["total"] == 7
    vistos += [r["public_id"] for r in primera["results"]]
    cursor = primera["next_cursor"]
    paginas = 1
    while cursor is not None:
        pagina = await _buscar(
            client, token, page_size=2, after=cursor, include_total="false"
        )
        assert pagina["total"] is None
        vistos += [r["public_id"] for r in pagina["results"]]
        cursor = pagina["next_cursor"]
        paginas += 1
    assert vistos == esperado
    assert paginas == 4
    # La ultima pagina (con una sola fila) no ofrece un cursor a la nada.
    assert len(pagina["results"]) == 1

    # Por offset, cada pagina tambien anuncia su cursor: el panel puede pasar
    # de ``page`` a ``after`` en cualquier momento.
    segunda = await _buscar(client, token, page=2, page_size=2)
    assert [r["public_id"] for r in segunda["results"]] == esperado[2:4]
    siguiente = await _buscar(client, token, page_size=2, after=segunda["next_cursor"])
    assert [r["public_id"] for r in siguiente["results"]] == esperado[4:6]


@pytest.mark.asyncio
async def test_un_cursor_invalido_es_422(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token = await _sembrar_turnos(client, test_session)
    valido = encode_cursor(datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc), "abc")
    sin_zona = base64.urlsafe_b64encode(b"2026-09-02T13:00:00|abc").decode()
    id_ajeno = base64.urlsafe_b64encode(b"2026-09-02T13:00:00+00:00|a b").decode()
    casos: list[dict[str, Any]] = [
        {"after": "no-es-un-cursor"},
        {"after": "x" * 500},
        {"after": sin_zona},
        {"after": id_ajeno},
        *({"after": desborde} for desborde in DESBORDES),
        {"after": valido, "page": 2},  # clave y salto a la vez: ambiguo
    ]
    for params in casos:
        res = await client.get(
            "/appointments/search", params=params, headers=auth_headers(token)
        )
        assert res.status_code == 422, (params, res.text)


@pytest.mark.asyncio
async def test_recorrer_el_fiado_por_cursor_da_lo_mismo_que_por_offset(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, deudor = await _tienda_con_deudor(client, test_session, slug="f308-fiado")
    await _cargar(client, token, deudor, cuantos=5)
    # Dos movimientos en el mismo instante: el id desempata.
    filas = (
        (
            await test_session.execute(
                select(CustomerLedger.id)
                .where(CustomerLedger.client_id == deudor)
                .order_by(CustomerLedger.id)
            )
        )
        .scalars()
        .all()
    )
    instante = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
    await test_session.execute(
        update(CustomerLedger)
        .where(CustomerLedger.id.in_(filas[1:3]))
        .values(created_at=instante)
    )
    await test_session.commit()
    url = f"/ledger/customers/{deudor}"

    todo = await client.get(url, params={"limit": 50}, headers=auth_headers(token))
    assert todo.status_code == 200, todo.text
    esperado = [m["public_id"] for m in todo.json()["movements"]]
    assert len(esperado) == 5 and todo.json()["next_cursor"] is None

    vistos: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor is not None:
            params["after"] = cursor
        pagina = await client.get(url, params=params, headers=auth_headers(token))
        assert pagina.status_code == 200, pagina.text
        cuerpo = pagina.json()
        # El saldo y el total no dependen de la pagina.
        assert (cuerpo["balance"], cuerpo["total"]) == ("50.00", 5)
        vistos += [m["public_id"] for m in cuerpo["movements"]]
        cursor = cuerpo["next_cursor"]
        if cursor is None:
            break
    assert vistos == esperado

    ambiguo = await client.get(
        url,
        params={"limit": 2, "offset": 2, "after": encode_cursor(instante, filas[0])},
        headers=auth_headers(token),
    )
    assert ambiguo.status_code == 422, ambiguo.text
    for invalido in ("%%%", *DESBORDES):
        roto = await client.get(
            url, params={"after": invalido}, headers=auth_headers(token)
        )
        assert roto.status_code == 422, (invalido, roto.text)


@pytest.mark.asyncio
async def test_sin_acceso_al_fiado_es_403_aunque_el_cursor_este_roto(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """La autorizacion va antes que la validacion del cursor: un usuario sin
    acceso financiero no aprende nada del formato del cursor (403, no 422)."""
    _, deudor = await _tienda_con_deudor(client, test_session, slug="f308-recep")
    duenio = (
        await test_session.execute(select(User).where(User.id == deudor))
    ).scalar_one()
    test_session.add(
        User(
            email="recepcion-f308@test.com",
            hashed_password=hash_password("Password123!"),
            first_name="Recep",
            last_name="Cion",
            role=UserRole.RECEPTIONIST,
            store_id=duenio.store_id,
        )
    )
    await test_session.commit()
    login = await client.post(
        "/auth/login",
        json={"email": "recepcion-f308@test.com", "password": "Password123!"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    for invalido in ("%%%", DESBORDES[0]):
        res = await client.get(
            f"/ledger/customers/{deudor}",
            params={"after": invalido},
            headers=auth_headers(token),
        )
        assert res.status_code == 403, (invalido, res.text)
