"""El profesional ve y carga fiado, y busca clientes sin ver cuentas del personal.

Decision de Mateo (2026-09-25, D3). El fiado (``/ledger/*``) ya admitia al
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

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.ledger.model import CustomerLedger
from modules.users.model import User

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
    # Decision de Mateo (revision de fix/legal-datos, 2026-09-25): el
    # profesional busca SOLO por nombre. Con digitos del telefono, ampliando
    # q de a uno, reconstruia el numero que la respuesta enmascara.
    assert por_telefono.json() == []
    ana = por_nombre.json()[0]
    assert ana["name"] == "Ana Fiadora"
    # L3-03 (2026-09-25): el profesional ve el telefono enmascarado (ultimos 3
    # digitos) y no ve el email; buscar por digitos sigue funcionando.
    assert ana["phone"] == "***001"
    assert ana["email"] is None
    assert set(ana) == {"public_id", "name", "email", "phone"}
    for res in (todos, por_nombre, por_telefono, con_rol):
        assert "4444000" not in res.text and "@example.com" not in res.text


@pytest.mark.asyncio
async def test_el_admin_ve_el_contacto_completo_en_el_buscador(
    client: AsyncClient,
) -> None:
    t = await _tienda(client, "fiado-admin-contacto")

    res = await client.get(
        "/ledger/clients", headers=auth_headers(t.admin), params={"q": "4444 0001"}
    )

    assert res.status_code == 200, res.text
    [ana] = res.json()
    assert ana["phone"] == "+5491144440001"
    assert ana["email"] == "ana-fiado-admin-contacto@example.com"


@pytest.mark.asyncio
async def test_sin_nombre_el_profesional_no_ve_el_email_como_nombre(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El nombre caia al email o al telefono completos si faltaba: para el
    profesional cae al telefono enmascarado, en el buscador y en el resumen."""
    t = await _tienda(client, "fiado-sin-nombre")
    cliente = (
        await test_session.execute(select(User).where(User.id == t.cliente))
    ).scalar_one()
    cliente.first_name = None
    cliente.last_name = None
    await test_session.commit()
    carga = await client.post(
        f"/ledger/customers/{t.cliente}/movements",
        headers=t.profesional,
        json={"movement_type": "charge", "amount": "100.00"},
    )
    assert carga.status_code == 200, carga.text

    buscador = await client.get("/ledger/clients", headers=t.profesional)
    resumen = await client.get("/ledger/summary", headers=t.profesional)
    del_admin = await client.get("/ledger/summary", headers=auth_headers(t.admin))

    assert buscador.status_code == 200, buscador.text
    [sin_nombre] = [c for c in buscador.json() if c["public_id"] == t.cliente]
    assert sin_nombre["name"] == "***001"
    assert resumen.status_code == 200, resumen.text
    assert resumen.json()["top_debtors"][0]["client_name"] == "***001"
    for res in (buscador, resumen):
        assert "@example.com" not in res.text and "4444000" not in res.text
    assert del_admin.json()["top_debtors"][0]["client_name"] == (
        "ana-fiado-sin-nombre@example.com"
    )


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


@pytest.mark.asyncio
async def test_el_fiado_es_solo_de_clientes_no_del_personal(
    client: AsyncClient,
) -> None:
    """Revision de perf/f4-pay (2026-09-25, #6): ``ensure_store_client``
    aceptaba cualquier usuario de la tienda. El personal y los admins no son
    destinatarios de fiado: 404 neutro, igual que un id de otra tienda."""
    t = await _tienda(client, "fiado-solo-clientes")
    del_personal = sorted(t.personal)

    for usuario in del_personal:
        carga = await client.post(
            f"/ledger/customers/{usuario}/movements",
            headers=t.profesional,
            json={"movement_type": "charge", "amount": "10.00"},
        )
        cuenta = await client.get(f"/ledger/customers/{usuario}", headers=t.profesional)
        for res in (carga, cuenta):
            assert res.status_code == 404, res.text
            assert res.json()["error_code"] == "RESOURCE_NOT_FOUND", res.text


@pytest.mark.asyncio
async def test_un_movimiento_viejo_sobre_el_personal_se_puede_revertir(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Revision de perf/f4-pay (2026-09-25, #7): decision del coordinador.
    ``ensure_store_client`` cierra leer y cargar fiado sobre el personal, pero
    ``reverse_movement`` NO lo llama a proposito: los movimientos que quedaron
    cargados a una cuenta del personal antes de ese cierre se pueden revertir
    (limpieza). Se sigue exigiendo que el movimiento sea de la tienda y de esa
    cuenta."""
    t = await _tienda(client, "fiado-revierte-legado")
    del_personal = sorted(t.personal)[0]
    usuario = (
        await test_session.execute(select(User).where(User.id == del_personal))
    ).scalar_one()
    legado = CustomerLedger(
        store_id=usuario.store_id,
        client_id=del_personal,
        movement_type="charge",
        amount=Decimal("10.00"),
        balance_after=Decimal("10.00"),
        notes="Cargado antes del cierre",
    )
    test_session.add(legado)
    await test_session.commit()

    res = await client.post(
        f"/ledger/customers/{del_personal}/movements/{legado.id}/reverse",
        headers=t.profesional,
    )

    assert res.status_code == 200, res.text
    assert res.json()["balance_after"] == "0.00"


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["44", "444", "4444", "44440001", "+54 9 11 4444"])
async def test_el_profesional_no_reconstruye_el_telefono_buscando_por_digitos(
    client: AsyncClient, q: str
) -> None:
    """Decision de Mateo (revision de fix/legal-datos, 2026-09-25): ampliar
    ``q`` de a un digito y mirar si el cliente sigue apareciendo reconstruia
    el numero enmascarado. Para el profesional ``q`` busca solo por nombre;
    el admin sigue buscando por telefono."""
    t = await _tienda(client, f"fiado-oraculo-{len(q)}-{q[:2]}")

    profesional = await client.get(
        "/ledger/clients", headers=t.profesional, params={"q": q}
    )
    admin = await client.get(
        "/ledger/clients", headers=auth_headers(t.admin), params={"q": q}
    )

    assert profesional.status_code == 200, profesional.text
    assert profesional.json() == []
    assert admin.status_code == 200, admin.text
    assert t.cliente in {c["public_id"] for c in admin.json()}
