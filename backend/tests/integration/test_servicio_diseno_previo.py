"""Servicio que requiere diseno previo (2026-10-21, portal publico, S7).

Pedido de Mateo: "el diseño previo es una configuracion de simplemente un
mensaje, que indique tipo. si el diseño se aprueba o no, el pago o seña se
hace igual en ambos casos". Son dos datos del servicio y nada mas: el cobro,
la sena, los canales y los estados del turno no cambian.

- ``requires_prior_design``: NOT NULL, default false (en la base tambien:
  las filas viejas y el codigo anterior siguen funcionando).
- ``prior_design_message``: texto opcional de hasta 500 caracteres que sale
  al portal publico, asi que pasa por la regla 19 (``reject_control_chars``);
  se recorta y un texto vacio queda en null.
"""

from datetime import datetime, timezone
from typing import Any, cast

import pytest
import ulid
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.services.model import Service
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_staff,
    register_and_login,
)

BASE = {"name": "Unas esculpidas", "duration_minutes": 90, "price": 20000}
MENSAJE = "Mandanos por WhatsApp una foto del diseño que querés."


async def _crear(client: AsyncClient, token: str, **extra: Any) -> dict[str, Any]:
    res = await client.post(
        "/services/", headers=auth_headers(token), json={**BASE, **extra}
    )
    assert res.status_code == 201, res.text
    return cast(dict[str, Any], res.json())


async def _leer(client: AsyncClient, token: str, public_id: str) -> dict[str, Any]:
    res = await client.get(f"/services/{public_id}", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    return cast(dict[str, Any], res.json())


async def _patch(
    client: AsyncClient, token: str, public_id: str, body: dict[str, Any]
) -> Any:
    return await client.patch(
        f"/services/{public_id}", headers=auth_headers(token), json=body
    )


async def _fila(session: AsyncSession, public_id: str) -> Service:
    session.expire_all()
    return (
        await session.execute(select(Service).where(Service.public_id == public_id))
    ).scalar_one()


@pytest.mark.asyncio
async def test_un_servicio_nuevo_no_requiere_diseno_previo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="dp-default", email="dp-default@example.com"
    )
    creado = await _crear(client, token)

    assert creado["requires_prior_design"] is False
    assert creado["prior_design_message"] is None
    leido = await _leer(client, token, creado["public_id"])
    assert leido["requires_prior_design"] is False
    assert leido["prior_design_message"] is None
    fila = await _fila(test_session, creado["public_id"])
    assert fila.requires_prior_design is False
    assert fila.prior_design_message is None


@pytest.mark.asyncio
async def test_una_fila_escrita_sin_las_columnas_queda_en_false(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """El default vive en la base: lo que inserta el codigo anterior (sin las
    columnas nuevas) nace sin diseno previo y se lee igual."""
    store_public_id, token = await register_and_login(
        client, slug="dp-legado", email="dp-legado@example.com"
    )
    tienda = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    ahora = datetime.now(timezone.utc)
    public_id = str(ulid.ULID())
    await test_session.execute(
        text(
            "INSERT INTO services (id, public_id, store_id, name, "
            "duration_minutes, price, deposit_mode, deposit_type, is_active, "
            "created_at, updated_at) VALUES (:id, :public_id, :store_id, "
            "'Legado', 30, 1500, 'none', 'percent', :activo, :ahora, :ahora)"
        ),
        {
            "id": str(ulid.ULID()),
            "public_id": public_id,
            "store_id": tienda.id,
            "activo": True,
            "ahora": ahora,
        },
    )
    await test_session.commit()

    leido = await _leer(client, token, public_id)
    assert leido["requires_prior_design"] is False
    assert leido["prior_design_message"] is None


@pytest.mark.asyncio
async def test_alta_con_diseno_previo_y_mensaje_recortado(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="dp-alta", email="dp-alta@example.com"
    )
    creado = await _crear(
        client,
        token,
        requires_prior_design=True,
        prior_design_message=f"  {MENSAJE}\n",
    )

    assert creado["requires_prior_design"] is True
    assert creado["prior_design_message"] == MENSAJE
    fila = await _fila(test_session, creado["public_id"])
    assert fila.requires_prior_design is True
    assert fila.prior_design_message == MENSAJE


@pytest.mark.asyncio
@pytest.mark.parametrize("vacio", ["", "   ", "\n\t"])
async def test_alta_con_mensaje_vacio_queda_en_null(
    client: AsyncClient, vacio: str
) -> None:
    _, token = await register_and_login(
        client, slug=f"dp-vacio-{len(vacio)}", email=f"dp-vacio-{len(vacio)}@e.com"
    )
    creado = await _crear(
        client, token, requires_prior_design=True, prior_design_message=vacio
    )
    assert creado["prior_design_message"] is None


@pytest.mark.asyncio
async def test_patch_prende_cambia_y_borra_el_mensaje(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="dp-patch", email="dp-patch@example.com"
    )
    public_id = (await _crear(client, token))["public_id"]

    prender = await _patch(
        client,
        token,
        public_id,
        {"requires_prior_design": True, "prior_design_message": MENSAJE},
    )
    assert prender.status_code == 200, prender.text
    assert prender.json()["requires_prior_design"] is True
    assert prender.json()["prior_design_message"] == MENSAJE

    cambiar = await _patch(
        client, token, public_id, {"prior_design_message": " Traé tu referencia. "}
    )
    assert cambiar.status_code == 200, cambiar.text
    assert cambiar.json()["prior_design_message"] == "Traé tu referencia."
    assert cambiar.json()["requires_prior_design"] is True

    borrar = await _patch(client, token, public_id, {"prior_design_message": None})
    assert borrar.status_code == 200, borrar.text
    assert borrar.json()["prior_design_message"] is None
    fila = await _fila(test_session, public_id)
    assert fila.prior_design_message is None
    assert fila.requires_prior_design is True

    await _patch(client, token, public_id, {"prior_design_message": MENSAJE})
    vaciar = await _patch(client, token, public_id, {"prior_design_message": "  "})
    assert vaciar.status_code == 200, vaciar.text
    assert vaciar.json()["prior_design_message"] is None

    apagar = await _patch(client, token, public_id, {"requires_prior_design": False})
    assert apagar.status_code == 200, apagar.text
    assert (await _leer(client, token, public_id))["requires_prior_design"] is False


@pytest.mark.asyncio
async def test_patch_con_null_en_requires_prior_design_es_422(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="dp-null", email="dp-null@example.com"
    )
    public_id = (await _crear(client, token, requires_prior_design=True))["public_id"]

    res = await _patch(client, token, public_id, {"requires_prior_design": None})

    assert res.status_code == 422, res.text
    assert res.json()["error_code"] == "VALIDATION_ERROR"
    assert (await _fila(test_session, public_id)).requires_prior_design is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "veneno",
    [
        pytest.param("Mandá " + chr(0x202E) + "tu diseño", id="bidi-override"),
        pytest.param("Man" + chr(0x200B) + "dá", id="zero-width"),
        pytest.param("Man\x00dá", id="nul"),
    ],
)
async def test_el_mensaje_rechaza_control_chars(
    client: AsyncClient, test_session: AsyncSession, veneno: str
) -> None:
    _, token = await register_and_login(
        client, slug="dp-veneno", email="dp-veneno@example.com"
    )

    alta = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={**BASE, "requires_prior_design": True, "prior_design_message": veneno},
    )
    assert alta.status_code == 422, alta.text
    assert alta.json()["error_code"] == "VALIDATION_ERROR"
    test_session.expire_all()
    assert (await test_session.execute(select(Service.id))).all() == []

    public_id = (await _crear(client, token, prior_design_message=MENSAJE))["public_id"]
    cambio = await _patch(client, token, public_id, {"prior_design_message": veneno})
    assert cambio.status_code == 422, cambio.text
    assert cambio.json()["error_code"] == "VALIDATION_ERROR"
    assert (await _fila(test_session, public_id)).prior_design_message == MENSAJE


@pytest.mark.asyncio
async def test_el_mensaje_tiene_tope_de_500_caracteres(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="dp-tope", email="dp-tope@example.com"
    )

    justo = await _crear(client, token, prior_design_message="a" * 500)
    assert justo["prior_design_message"] == "a" * 500

    largo = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={**BASE, "prior_design_message": "a" * 501},
    )
    assert largo.status_code == 422, largo.text
    assert largo.json()["error_code"] == "VALIDATION_ERROR"

    cambio = await _patch(
        client, token, justo["public_id"], {"prior_design_message": "b" * 501}
    )
    assert cambio.status_code == 422, cambio.text
    assert cambio.json()["error_code"] == "VALIDATION_ERROR"
    fila = await _fila(test_session, justo["public_id"])
    assert fila.prior_design_message == "a" * 500


@pytest.mark.asyncio
async def test_el_catalogo_publico_expone_el_diseno_previo(
    client: AsyncClient,
) -> None:
    store_public_id, token = await register_and_login(
        client, slug="dp-publico", email="dp-publico@example.com"
    )
    con_diseno = (
        await _crear(
            client, token, requires_prior_design=True, prior_design_message=MENSAJE
        )
    )["public_id"]
    sin_diseno = (await _crear(client, token, name="Esmaltado"))["public_id"]
    staff = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Natalia",
            "first_name": "Natalia",
            "last_name": "Pro",
            "email": "dp-publico-pro@example.com",
            "service_ids": [con_diseno, sin_diseno],
        },
    )
    assert staff.status_code == 201, staff.text

    res = await client.get(
        "/public/services", params={"store_public_id": store_public_id}
    )

    assert res.status_code == 200, res.text
    por_id = {s["public_id"]: s for s in res.json()}
    assert por_id[con_diseno]["requires_prior_design"] is True
    assert por_id[con_diseno]["prior_design_message"] == MENSAJE
    assert por_id[sin_diseno]["requires_prior_design"] is False
    assert por_id[sin_diseno]["prior_design_message"] is None


@pytest.mark.asyncio
async def test_patch_de_otro_campo_no_toca_el_diseno_previo(
    client: AsyncClient,
) -> None:
    """Comportamiento previo del PATCH (B6-04): lo ausente no se toca. Vale
    para los campos nuevos y para los de siempre, y el catalogo publico sigue
    publicando lo de antes."""
    store_public_id, token = await register_and_login(
        client, slug="dp-ausente", email="dp-ausente@example.com"
    )
    creado = await _crear(
        client,
        token,
        description="Con esmaltado",
        requires_prior_design=True,
        prior_design_message=MENSAJE,
    )
    await create_staff(
        client, token, creado["public_id"], email="dp-ausente-pro@example.com"
    )

    res = await _patch(client, token, creado["public_id"], {"price": 25000})

    assert res.status_code == 200, res.text
    guardado = await _leer(client, token, creado["public_id"])
    assert guardado["price"] == 25000
    for campo in ("name", "description", "duration_minutes", "deposit_mode"):
        assert guardado[campo] == creado[campo], campo
    assert guardado["requires_prior_design"] is True
    assert guardado["prior_design_message"] == MENSAJE
    publico = await client.get(
        "/public/services", params={"store_public_id": store_public_id}
    )
    (servicio,) = publico.json()
    assert servicio["name"] == BASE["name"]
    assert servicio["description"] == "Con esmaltado"
    assert servicio["price"] == 25000
    assert servicio["addons"] == []
