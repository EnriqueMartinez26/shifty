"""Adicionales del servicio en el panel y en el catalogo publico (2026-10-14).

Decision de Mateo (2026-10-14): un servicio puede tener adicionales con precio
(``service_addons``): suman precio, nunca tiempo. El panel los carga en el alta
y en el PATCH del servicio (``addons`` reemplaza el conjunto entero, la
posicion es el indice) y ``/public/services`` los muestra.

Se fija: topes de cada campo (regla 9: ``ge`` Y ``le``; sin sub-centavos),
texto sin caracteres de control (regla 19), nombres unicos, reemplazo del
conjunto, y aislamiento entre tiendas (el adicional de otra tienda no se ve ni
se puede elegir).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment
from modules.services.model import ServiceAddon
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_staff,
    register_and_login,
)

ADICIONALES = [
    {"name": "Strass", "unit_price": 500, "max_quantity": 10},
    {"name": "Diseño", "unit_price": 1500.5},
]


async def _crear_servicio(
    client: AsyncClient, token: str, addons: Any = ADICIONALES
) -> Any:
    res = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={
            "name": "Uñas",
            "duration_minutes": 60,
            "price": 27000,
            "addons": addons,
        },
    )
    return res


async def _tienda(client: AsyncClient, slug: str) -> tuple[str, str]:
    return await register_and_login(client, slug=slug, email=f"{slug}@t.com")


@pytest.mark.asyncio
async def test_el_alta_guarda_los_adicionales_en_orden(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _store, token = await _tienda(client, "adic-alta")

    res = await _crear_servicio(client, token)

    assert res.status_code == 201, res.text
    addons = res.json()["addons"]
    assert [
        (a["name"], a["unit_price"], a["max_quantity"], a["position"]) for a in addons
    ] == [
        ("Strass", 500.0, 10, 0),
        ("Diseño", 1500.5, 1, 1),
    ]
    assert all(isinstance(a["id"], str) and a["id"] for a in addons)
    servicio = res.json()["public_id"]
    # El GET, el listado y la base dicen lo mismo.
    uno = await client.get(f"/services/{servicio}", headers=auth_headers(token))
    assert uno.json()["addons"] == addons
    listado = await client.get("/services/", headers=auth_headers(token))
    assert listado.json()[0]["addons"] == addons
    filas = (await test_session.execute(select(ServiceAddon))).scalars().all()
    assert sorted(f.id for f in filas) == sorted(a["id"] for a in addons)


@pytest.mark.asyncio
async def test_un_servicio_sin_adicionales_responde_lista_vacia(
    client: AsyncClient,
) -> None:
    _store, token = await _tienda(client, "adic-sin")

    res = await _crear_servicio(client, token, addons=None)

    assert res.status_code == 201, res.text
    assert res.json()["addons"] == []


@pytest.mark.asyncio
async def test_el_patch_reemplaza_el_conjunto_y_sin_el_campo_no_lo_toca(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _store, token = await _tienda(client, "adic-patch")
    creado = await _crear_servicio(client, token)
    servicio = creado.json()["public_id"]
    viejos = {a["id"] for a in creado.json()["addons"]}

    # Sin ``addons`` (o con null) el conjunto no cambia.
    for cuerpo in ({"price": 28000}, {"addons": None}):
        res = await client.patch(
            f"/services/{servicio}", headers=auth_headers(token), json=cuerpo
        )
        assert res.status_code == 200, res.text
        assert {a["id"] for a in res.json()["addons"]} == viejos

    # Con ``addons`` se reemplaza entero: ids nuevos, posicion = indice, y un
    # ``id`` que venga del formulario se ignora.
    res = await client.patch(
        f"/services/{servicio}",
        headers=auth_headers(token),
        json={
            "addons": [
                {"id": next(iter(viejos)), "name": "Brillo", "unit_price": 200},
                {"name": "Strass", "unit_price": 600, "max_quantity": 5},
            ]
        },
    )
    assert res.status_code == 200, res.text
    nuevos = res.json()["addons"]
    assert [(a["name"], a["unit_price"], a["position"]) for a in nuevos] == [
        ("Brillo", 200.0, 0),
        ("Strass", 600.0, 1),
    ]
    assert not ({a["id"] for a in nuevos} & viejos)
    test_session.expire_all()
    filas = (await test_session.execute(select(ServiceAddon))).scalars().all()
    assert len(filas) == 2

    # Una lista vacia los quita todos.
    res = await client.patch(
        f"/services/{servicio}", headers=auth_headers(token), json={"addons": []}
    )
    assert res.status_code == 200, res.text
    assert res.json()["addons"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adicional",
    [
        pytest.param({"name": "X", "unit_price": -1}, id="precio-negativo"),
        pytest.param({"name": "X", "unit_price": 1_000_000.01}, id="precio-tope"),
        pytest.param({"name": "X", "unit_price": 10.001}, id="sub-centavo"),
        pytest.param({"name": "X", "unit_price": 1, "max_quantity": 0}, id="max-0"),
        pytest.param({"name": "X", "unit_price": 1, "max_quantity": 100}, id="max-100"),
        pytest.param({"name": "", "unit_price": 1}, id="nombre-vacio"),
        pytest.param({"name": "   ", "unit_price": 1}, id="nombre-en-blanco"),
        pytest.param({"name": "x" * 101, "unit_price": 1}, id="nombre-largo"),
        pytest.param({"name": "Strass‮", "unit_price": 1}, id="bidi"),
        pytest.param({"name": "Stra​ss", "unit_price": 1}, id="zero-width"),
        pytest.param({"name": "Strass\x00", "unit_price": 1}, id="nul"),
        pytest.param({"unit_price": 1}, id="sin-nombre"),
        pytest.param({"name": "X"}, id="sin-precio"),
    ],
)
async def test_un_adicional_fuera_de_los_topes_es_422(
    client: AsyncClient, test_session: AsyncSession, adicional: dict[str, Any]
) -> None:
    _store, token = await _tienda(client, "adic-topes")

    res = await _crear_servicio(client, token, addons=[adicional])

    assert res.status_code == 422, res.text
    creado = await _crear_servicio(client, token, addons=[])
    assert creado.status_code == 201, creado.text
    patch = await client.patch(
        f"/services/{creado.json()['public_id']}",
        headers=auth_headers(token),
        json={"addons": [adicional]},
    )
    assert patch.status_code == 422, patch.text
    assert (await test_session.execute(select(ServiceAddon))).scalars().all() == []


@pytest.mark.asyncio
async def test_los_limites_del_conjunto(client: AsyncClient) -> None:
    _store, token = await _tienda(client, "adic-conjunto")
    veinte = [{"name": f"A{i}", "unit_price": 1} for i in range(20)]

    assert (await _crear_servicio(client, token, addons=veinte)).status_code == 201
    veintiuno = veinte + [{"name": "A20", "unit_price": 1}]
    assert (await _crear_servicio(client, token, addons=veintiuno)).status_code == 422
    # Nombres repetidos, sin distinguir mayusculas ni espacios.
    repetidos = [
        {"name": "Strass", "unit_price": 1},
        {"name": " strass ", "unit_price": 2},
    ]
    assert (await _crear_servicio(client, token, addons=repetidos)).status_code == 422


@pytest.mark.asyncio
async def test_el_catalogo_publico_muestra_los_adicionales_de_su_tienda(
    client: AsyncClient,
) -> None:
    store_a, token_a = await _tienda(client, "adic-pub-a")
    store_b, token_b = await _tienda(client, "adic-pub-b")
    creado_a = await _crear_servicio(client, token_a)
    creado_b = await _crear_servicio(
        client, token_b, addons=[{"name": "Brillo", "unit_price": 100}]
    )
    for token, creado, email in (
        (token_a, creado_a, "pro-a@t.com"),
        (token_b, creado_b, "pro-b@t.com"),
    ):
        await create_staff(client, token, creado.json()["public_id"], email=email)

    pub_a = await client.get(f"/public/services?store_public_id={store_a}")
    pub_b = await client.get(f"/public/services?store_public_id={store_b}")

    assert pub_a.status_code == pub_b.status_code == 200
    assert pub_a.json()[0]["addons"] == creado_a.json()["addons"]
    assert [a["name"] for a in pub_b.json()[0]["addons"]] == ["Brillo"]
    # El panel de B no ve el servicio (ni los adicionales) de A.
    ajeno = await client.get(
        f"/services/{creado_a.json()['public_id']}", headers=auth_headers(token_b)
    )
    assert ajeno.status_code == 404


@pytest.mark.asyncio
async def test_no_se_puede_elegir_el_adicional_de_otra_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _store_a, token_a = await _tienda(client, "adic-ajeno-a")
    store_b, token_b = await _tienda(client, "adic-ajeno-b")
    ajeno = (await _crear_servicio(client, token_a)).json()["addons"][0]["id"]
    servicio_b = cast(
        str, (await _crear_servicio(client, token_b, addons=[])).json()["public_id"]
    )
    staff_b = await create_staff(client, token_b, servicio_b, email="pro-ajeno@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token_b, staff_b, target_date=dia)

    res = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store_b,
            "service_id": servicio_b,
            "staff_id": staff_b,
            "starts_at": dia.replace(
                hour=12, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente",
            "client_phone": "+5491155500001",
            "client_email": "cliente-ajeno@example.com",
            "accepts_terms": True,
            "addons": [{"addon_id": ajeno, "quantity": 1}],
        },
    )

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "ADDON_UNAVAILABLE"
    assert (await test_session.execute(select(Appointment))).scalars().all() == []
