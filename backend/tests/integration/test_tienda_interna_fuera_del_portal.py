"""La tienda interna del SuperAdmin no existe para el portal publico.

2026-10-10. Sintoma: ``GET /api/public/stores/shifty-internal`` respondia 200
y ``/b/shifty-internal`` mostraba la vitrina. Esa tienda solo existe para
alojar las cuentas SuperAdmin (``scripts/bootstrap_superadmin.py`` la crea;
slug ``SUPERADMIN_STORE_SLUG``, por defecto ``shifty-internal``).

Criterio: la columna ``stores.is_internal``, que el bootstrap marca al crear o
reusar la tienda (y la migracion marca en la que ya existe con el slug por
defecto). No depende del slug ni de quienes son sus usuarios: ascender a
SuperAdmin al dueno de una tienda real no la esconde.

Todo endpoint publico que resuelve una tienda (vitrina, referencia de "Mis
turnos", servicios, profesionales, disponibilidad, previews, OTP, reserva,
lista de espera, historial del cliente) responde el MISMO 404 que una tienda
inexistente. El panel del SuperAdmin la sigue listando.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import ARGENTINA_TZ
from modules.stores.model import Store
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)

PASSWORD = "Password123!"
DESCONOCIDA = "01TIENDAINEXISTENTE0000000"
SERVICIO_DESCONOCIDO = "01SERVICIOINEXISTENTE00000"


class Interna:
    def __init__(self, slug: str, store: str, service: str, staff: str) -> None:
        self.slug = slug
        self.store = store
        self.service = service
        self.staff = staff


async def _tienda_interna(
    client: AsyncClient, session: AsyncSession, slug: str
) -> tuple[Interna, dict[str, str]]:
    """Como la deja el bootstrap: marcada interna y con su SuperAdmin.

    Se le cargan servicio y profesional para que, sin el filtro, cada endpoint
    tuviera algo que mostrar.
    """
    email = f"{slug}@t.com"
    store, token = await register_and_login(client, slug=slug, email=email)
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@t.com")
    fila = (
        await session.execute(select(Store).where(Store.public_id == store))
    ).scalar_one()
    fila.is_internal = True
    cuenta = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one()
    cuenta.is_global_admin = True
    await session.commit()
    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return Interna(slug, store, service, staff), auth_headers(
        str(login.json()["access_token"])
    )


def _sin_identificador(res: Response, *identificadores: str) -> Any:
    """El cuerpo del 404 con el identificador pedido reemplazado."""
    texto = res.text
    for valor in identificadores:
        texto = texto.replace(valor, "<id>")
    cuerpo = json.loads(texto)
    # El id de la peticion cambia en cada respuesta.
    if isinstance(cuerpo, dict):
        cuerpo.pop("request_id", None)
    return cuerpo


def _dia_local() -> str:
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    return dia.astimezone(ARGENTINA_TZ).date().isoformat()


def _inicio() -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(days=5))
        .replace(hour=15, minute=0, second=0, microsecond=0)
        .isoformat()
    )


async def _pedidos(
    client: AsyncClient, *, slug: str, store: str, service: str
) -> dict[str, Response]:
    """Un pedido por endpoint publico que resuelve una tienda."""
    reserva = {
        "store_public_id": store,
        "service_id": service,
        "starts_at": _inicio(),
        "client_name": "Cliente",
        "client_phone": "+5491155550101",
        "accepts_terms": True,
        "idempotency_key": f"interna-{store}",
    }
    espera = {
        "store_public_id": store,
        "service_id": service,
        "window_starts_at": _inicio(),
        "window_ends_at": (datetime.now(timezone.utc) + timedelta(days=6)).isoformat(),
        "client_name": "Cliente",
        "client_phone": "+5491155550101",
    }
    return {
        "vitrina": await client.get(f"/public/stores/{slug}"),
        "referencia": await client.get(f"/public/stores/{slug}/ref"),
        "servicios": await client.get(
            "/public/services", params={"store_public_id": store}
        ),
        "profesionales": await client.get(
            "/public/staff", params={"store_public_id": store}
        ),
        "disponibilidad": await client.get(
            "/public/availability",
            params={
                "store_public_id": store,
                "service_id": service,
                "date": _dia_local(),
            },
        ),
        "sena": await client.get(
            "/public/deposit/preview",
            params={
                "store_public_id": store,
                "service_id": service,
                "starts_at": _inicio(),
            },
        ),
        "promocion": await client.get(
            "/public/promotions/preview",
            params={"store_public_id": store, "service_id": service, "code": "PROMO"},
        ),
        "otp": await client.post(
            "/public/otp/request",
            json={
                "store_public_id": store,
                "phone": "+5491155550101",
                "email": "cliente@example.com",
            },
        ),
        "reserva": await client.post("/public/appointments", json=reserva),
        "espera": await client.post("/public/waitlist", json=espera),
        "historial": await client.get(
            f"/public/client/{store}/5491155550101/appointments"
        ),
    }


@pytest.mark.asyncio
async def test_todo_el_portal_responde_el_404_de_una_tienda_inexistente(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    interna, _ = await _tienda_interna(client, test_session, "interna-portal")

    suyas = await _pedidos(
        client, slug=interna.slug, store=interna.store, service=interna.service
    )
    inexistentes = await _pedidos(
        client, slug="no-existe-interna", store=DESCONOCIDA, service=interna.service
    )

    for nombre, res in suyas.items():
        otra = inexistentes[nombre]
        assert res.status_code == 404, (nombre, res.status_code, res.text)
        assert res.status_code == otra.status_code, (nombre, otra.text)
        assert _sin_identificador(
            res, interna.slug, interna.store
        ) == _sin_identificador(otra, "no-existe-interna", DESCONOCIDA), nombre


@pytest.mark.asyncio
async def test_sus_servicios_son_un_servicio_inexistente(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Sin ``store_public_id`` el portal resuelve la tienda por el servicio."""
    interna, _ = await _tienda_interna(client, test_session, "interna-servicio")

    suyo = await client.get("/public/staff", params={"service_id": interna.service})
    otro = await client.get(
        "/public/staff", params={"service_id": SERVICIO_DESCONOCIDO}
    )

    assert suyo.status_code == 404, suyo.text
    assert _sin_identificador(suyo, interna.service) == _sin_identificador(
        otro, SERVICIO_DESCONOCIDO
    )
    reserva = await client.post(
        "/public/appointments",
        json={
            "service_id": interna.service,
            "staff_id": interna.staff,
            "starts_at": _inicio(),
            "client_name": "Cliente",
            "client_phone": "+5491155550102",
            "accepts_terms": True,
            "idempotency_key": "interna-servicio-1",
        },
    )
    assert reserva.status_code == 404, reserva.text


@pytest.mark.asyncio
async def test_el_superadmin_la_sigue_viendo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    interna, headers = await _tienda_interna(client, test_session, "interna-panel")

    lista = await client.get(
        "/superadmin/stores", headers=headers, params={"search": "interna-panel"}
    )
    detalle = await client.get(f"/superadmin/stores/{interna.store}", headers=headers)

    assert lista.status_code == 200, lista.text
    assert interna.store in {s["public_id"] for s in lista.json()}
    assert detalle.status_code == 200, detalle.text
    assert detalle.json()["slug"] == interna.slug


@pytest.mark.asyncio
async def test_una_tienda_comun_sigue_publica(client: AsyncClient) -> None:
    """Control: el filtro no esconde a las tiendas de verdad."""
    store, token = await register_and_login(
        client, slug="comun-publica", email="comun-publica@t.com"
    )
    await create_service(client, token)

    assert (await client.get("/public/stores/comun-publica")).status_code == 200
    servicios = await client.get("/public/services", params={"store_public_id": store})
    assert servicios.status_code == 200, servicios.text


@pytest.mark.asyncio
async def test_el_bootstrap_crea_la_tienda_interna(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    from scripts.bootstrap_superadmin import get_or_create_internal_store

    store = await get_or_create_internal_store(
        test_session, "bootstrap-interna", "Shifty Internal"
    )
    await test_session.commit()

    assert store.is_internal is True
    assert (await client.get("/public/stores/bootstrap-interna")).status_code == 404
    # Idempotente: la segunda corrida reusa la misma.
    otra = await get_or_create_internal_store(
        test_session, "bootstrap-interna", "Shifty Internal"
    )
    assert otra.id == store.id


@pytest.mark.asyncio
async def test_el_bootstrap_no_esconde_una_tienda_real_con_ese_slug(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """``SUPERADMIN_STORE_SLUG`` mal puesto no borra del portal a una tienda real."""
    from scripts.bootstrap_superadmin import get_or_create_internal_store

    await register_and_login(client, slug="real-con-slug", email="real-slug@t.com")

    store = await get_or_create_internal_store(
        test_session, "real-con-slug", "Shifty Internal"
    )
    await test_session.commit()

    assert store.is_internal is False
    assert (await client.get("/public/stores/real-con-slug")).status_code == 200
