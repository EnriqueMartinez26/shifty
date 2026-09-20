"""B6-02 (2026-09-19): la terna de sena del servicio no tenia validacion cruzada.

Sintoma: ``deposit_mode``/``deposit_type``/``deposit_amount`` se validaban
cada uno por separado. Dos combinaciones llegaban a la base:
(a) ``percent`` con ``deposit_amount=500`` -> la reserva publica generaba un
link de Mercado Pago por 5 veces el precio del servicio;
(b) ``required`` sin monto (``null`` o 0) con tipo ``percent``/``fixed`` -> el
importe calculado era 0, la reserva no pedia sena y un servicio marcado
"sena obligatoria" se reservaba sin sena y sin aviso. Con
``optional`` el mismo hueco ofrecia una sena opcional de 0.

Decision: ``percent`` se acota a 100 en el schema y ``required``/``optional``
sin monto es 422 (no se normaliza a ``none``: el dueno pidio sena y tiene que
ver el error). En el PATCH se valida contra los valores actuales cuando se envia
cualquiera de los tres campos; un PATCH que no toca la sena no se bloquea
aunque la fila vieja sea invalida.
"""

from typing import Any, cast

import pytest
import ulid
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.services.model import Service
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


def _payload(mode: str, tipo: str, monto: float | None) -> dict[str, Any]:
    return {
        "name": "Corte",
        "duration_minutes": 30,
        "price": 10000,
        "deposit_mode": mode,
        "deposit_type": tipo,
        "deposit_amount": monto,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "tipo", "monto", "esperado"),
    [
        # percent acotado a 100, con cualquier modo.
        ("required", "percent", 100, 201),
        ("required", "percent", 100.01, 422),
        ("required", "percent", 500, 422),
        ("optional", "percent", 101, 422),
        ("none", "percent", 500, 422),
        # required necesita monto salvo con full.
        ("required", "percent", None, 422),
        ("required", "fixed", None, 422),
        ("required", "percent", 0, 422),
        ("required", "fixed", 0, 422),
        ("required", "full", None, 201),
        ("required", "fixed", 500000, 201),
        ("required", "percent", 30, 201),
        # optional tambien necesita monto: una sena opcional de 0 no existe.
        ("optional", "percent", None, 422),
        ("optional", "fixed", None, 422),
        ("optional", "percent", 0, 422),
        ("optional", "fixed", 0, 422),
        ("optional", "full", None, 201),
        # none no cobra: el monto no importa.
        ("none", "percent", None, 201),
        ("none", "fixed", 0, 201),
        # fixed no tiene tope 100 (se recorta al precio al cobrar).
        ("optional", "fixed", 15000, 201),
    ],
)
async def test_alta_valida_la_terna_de_sena(
    client: AsyncClient,
    mode: str,
    tipo: str,
    monto: float | None,
    esperado: int,
) -> None:
    _, token = await register_and_login(
        client, slug="b6-02-alta", email="b6-02-alta@example.com"
    )
    res = await client.post(
        "/services/", headers=auth_headers(token), json=_payload(mode, tipo, monto)
    )
    assert res.status_code == esperado, res.text
    if esperado == 422:
        assert res.json()["error_code"] == "VALIDATION_ERROR"


async def _crear(
    client: AsyncClient, token: str, mode: str, tipo: str, monto: float | None
) -> str:
    res = await client.post(
        "/services/", headers=auth_headers(token), json=_payload(mode, tipo, monto)
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


async def _sena(client: AsyncClient, token: str, public_id: str) -> tuple[Any, ...]:
    res = await client.get(f"/services/{public_id}", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    body = res.json()
    return (body["deposit_mode"], body["deposit_type"], body["deposit_amount"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("inicial", "patch", "esperado"),
    [
        # Servicio con sena obligatoria del 50%.
        (("required", "percent", 50), {"deposit_amount": 150}, 422),
        (("required", "percent", 50), {"deposit_amount": None}, 422),
        (("required", "percent", 50), {"deposit_amount": 0}, 422),
        (("required", "percent", 50), {"deposit_type": "fixed"}, 200),
        (("required", "percent", 50), {"deposit_type": "full"}, 200),
        (
            ("required", "percent", 50),
            {"deposit_type": "full", "deposit_amount": None},
            200,
        ),
        (("required", "percent", 50), {"deposit_mode": "none"}, 200),
        # Servicio sin sena: activar required sin monto no alcanza.
        (("none", "percent", None), {"deposit_mode": "required"}, 422),
        (
            ("none", "percent", None),
            {"deposit_mode": "required", "deposit_amount": 30},
            200,
        ),
        (("none", "fixed", 20000), {"deposit_type": "percent"}, 422),
        (("none", "fixed", 2000), {"deposit_mode": "required"}, 200),
        (("none", "percent", None), {"deposit_mode": "optional"}, 422),
        (("optional", "fixed", 2000), {"deposit_amount": None}, 422),
        (("optional", "fixed", 2000), {"deposit_mode": "none"}, 200),
    ],
)
async def test_patch_valida_contra_los_valores_actuales(
    client: AsyncClient,
    inicial: tuple[str, str, float | None],
    patch: dict[str, Any],
    esperado: int,
) -> None:
    _, token = await register_and_login(
        client, slug="b6-02-patch", email="b6-02-patch@example.com"
    )
    public_id = await _crear(client, token, *inicial)
    antes = await _sena(client, token, public_id)

    res = await client.patch(
        f"/services/{public_id}", headers=auth_headers(token), json=patch
    )
    assert res.status_code == esperado, res.text
    if esperado == 422:
        assert res.json()["error_code"] == "VALIDATION_ERROR"
        assert await _sena(client, token, public_id) == antes


@pytest.mark.asyncio
async def test_fila_vieja_invalida_se_edita_si_no_se_toca_la_sena(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="b6-02-legado", email="b6-02-legado@example.com"
    )
    store_id = (
        await test_session.execute(select(Store.id).where(Store.slug == "b6-02-legado"))
    ).scalar_one()
    servicio_id = str(ulid.ULID())
    test_session.add(
        Service(
            id=servicio_id,
            public_id=servicio_id,
            store_id=store_id,
            name="Legado",
            duration_minutes=30,
            price=10000,
            deposit_mode="optional",
            deposit_type="percent",
            deposit_amount=500,
        )
    )
    await test_session.commit()

    res = await client.patch(
        f"/services/{servicio_id}",
        headers=auth_headers(token),
        json={"name": "Legado renombrado"},
    )
    assert res.status_code == 200, res.text

    res = await client.patch(
        f"/services/{servicio_id}",
        headers=auth_headers(token),
        json={"deposit_mode": "required"},
    )
    assert res.status_code == 422, res.text
