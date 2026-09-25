"""El profesional ve y carga fiado, y busca clientes sin ver cuentas del personal.

Decision del dueno (2026-09-25, D3). El fiado (``/ledger/*``) ya admitia al
profesional (``_require_financial_access``: rol persistido ``admin`` o
``staff``), pero la pantalla no le servia: para elegir el cliente usaba
``GET /users/``, que es solo del admin y lista TODAS las cuentas de la tienda
(personal y admins incluidos).

``GET /ledger/clients`` es el buscador de clientes del fiado: misma puerta que
el resto del fiado (rol, ``feature_flags.ledger``, guarda de suspension) y
devuelve SOLO clientes activos de la tienda del usuario, con el rol forzado del
lado del servidor. ``GET /users/`` sigue siendo solo del admin (regla 16).
La recepcion sigue sin fiado (no es la misma puerta: la decide el dueno).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

PASSWORD = "Password123!"


async def _usuario(
    client: AsyncClient,
    admin: str,
    *,
    email: str,
    rol: str,
    nombre: str,
    apellido: str,
    telefono: str | None = None,
) -> str:
    cuerpo: dict[str, Any] = {
        "email": email,
        "password": PASSWORD,
        "first_name": nombre,
        "last_name": apellido,
        "role": rol,
    }
    if telefono:
        cuerpo["phone"] = telefono
    res = await client.post("/users/", headers=auth_headers(admin), json=cuerpo)
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    res = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return auth_headers(str(res.json()["access_token"]))


class _Tienda:
    def __init__(self) -> None:
        self.admin = ""
        self.cliente = ""
        self.otro_cliente = ""
        self.personal: set[str] = set()
        self.profesional: dict[str, str] = {}
        self.recepcion: dict[str, str] = {}


async def _tienda(client: AsyncClient, slug: str, *, fiado: bool = True) -> _Tienda:
    t = _Tienda()
    _store, t.admin = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    res = await client.put(
        "/stores/me/feature-flags",
        headers=auth_headers(t.admin),
        json={"ledger": fiado},
    )
    assert res.status_code == 200, res.text
    t.cliente = await _usuario(
        client,
        t.admin,
        email=f"ana-{slug}@example.com",
        rol="client",
        nombre="Ana",
        apellido="Fiadora",
        telefono="+5491144440001",
    )
    t.otro_cliente = await _usuario(
        client,
        t.admin,
        email=f"beto-{slug}@example.com",
        rol="client",
        nombre="Beto",
        apellido="Contado",
        telefono="+5491144440002",
    )
    pro = await _usuario(
        client,
        t.admin,
        email=f"pro-{slug}@example.com",
        rol="staff",
        nombre="Ana",
        apellido="Profesional",
        telefono="+5491144440003",
    )
    recepcion = await _usuario(
        client,
        t.admin,
        email=f"recepcion-{slug}@example.com",
        rol="receptionist",
        nombre="Ana",
        apellido="Recepcion",
    )
    t.personal = {pro, recepcion}
    t.profesional = await _login(client, f"pro-{slug}@example.com")
    t.recepcion = await _login(client, f"recepcion-{slug}@example.com")
    return t


@pytest.mark.asyncio
async def test_el_profesional_busca_solo_clientes_de_su_tienda(
    client: AsyncClient,
) -> None:
    t = await _tienda(client, "fiado-pro-busca")

    todos = await client.get("/ledger/clients", headers=t.profesional)
    por_nombre = await client.get(
        "/ledger/clients", headers=t.profesional, params={"q": "ana"}
    )
    por_telefono = await client.get(
        "/ledger/clients", headers=t.profesional, params={"q": "4444 0002"}
    )
    # Un ``role`` en el query no cambia nada: el rol lo fija el servidor.
    con_rol = await client.get(
        "/ledger/clients", headers=t.profesional, params={"role": "admin", "q": "ana"}
    )

    for res in (todos, por_nombre, por_telefono, con_rol):
        assert res.status_code == 200, res.text
    assert {c["public_id"] for c in todos.json()} == {t.cliente, t.otro_cliente}
    # "Ana" es tambien el nombre del profesional y de la recepcionista: el
    # buscador no los devuelve.
    assert [c["public_id"] for c in por_nombre.json()] == [t.cliente]
    assert [c["public_id"] for c in con_rol.json()] == [t.cliente]
    assert [c["public_id"] for c in por_telefono.json()] == [t.otro_cliente]
    ana = por_nombre.json()[0]
    assert ana["name"] == "Ana Fiadora"
    assert ana["phone"] == "+5491144440001"
    assert set(ana) == {"public_id", "name", "email", "phone"}


@pytest.mark.asyncio
async def test_el_profesional_ve_y_carga_fiado(client: AsyncClient) -> None:
    t = await _tienda(client, "fiado-pro-carga")

    carga = await client.post(
        f"/ledger/customers/{t.cliente}/movements",
        headers=t.profesional,
        json={"movement_type": "charge", "amount": "1500.00", "notes": "Corte"},
    )
    cuenta = await client.get(f"/ledger/customers/{t.cliente}", headers=t.profesional)
    resumen = await client.get("/ledger/summary", headers=t.profesional)

    assert carga.status_code == 200, carga.text
    assert cuenta.status_code == 200, cuenta.text
    assert cuenta.json()["balance"] == "1500.00"
    assert resumen.status_code == 200, resumen.text
    assert resumen.json()["debtors_count"] == 1


@pytest.mark.asyncio
async def test_el_profesional_sigue_sin_usuarios_ni_cuentas_del_personal(
    client: AsyncClient,
) -> None:
    """Regla 16: el buscador no abre ``/users/``."""
    t = await _tienda(client, "fiado-pro-users")

    listado = await client.get("/users/", headers=t.profesional)
    detalle = await client.get(f"/users/{t.cliente}", headers=t.profesional)

    assert listado.status_code == 403, listado.text
    assert detalle.status_code == 403, detalle.text


@pytest.mark.asyncio
async def test_la_recepcion_no_tiene_fiado_ni_buscador(client: AsyncClient) -> None:
    t = await _tienda(client, "fiado-recepcion")

    res = await client.get("/ledger/clients", headers=t.recepcion)

    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_sin_el_modulo_de_fiado_no_hay_buscador(client: AsyncClient) -> None:
    t = await _tienda(client, "fiado-apagado", fiado=False)

    res = await client.get("/ledger/clients", headers=t.profesional)

    assert res.status_code == 403, res.text
    assert res.json()["error_code"] == "FEATURE_DISABLED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params", [{"q": "a"}, {"q": "an\x00a"}, {"limit": 0}, {"limit": 101}]
)
async def test_el_buscador_valida_la_entrada(
    client: AsyncClient, params: dict[str, Any]
) -> None:
    t = await _tienda(client, f"fiado-422-{len(str(params))}")

    res = await client.get("/ledger/clients", headers=t.profesional, params=params)

    assert res.status_code == 422, res.text
