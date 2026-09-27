"""Cambiar el slug al de otra tienda responde 409 neutro, no un 400 imposible.

AUD2-B3-15, 2026-09-20. Dos cosas en el mismo bloque de
``modules/stores/router.py``:

1. El pre-chequeo ``select(Store).where(Store.slug == slug)`` corria con el
   contexto de tenant del admin, y ``stores_rls_policy`` restringe la tabla a
   ``id = current_setting('app.current_store_id')``
   (``alembic/versions/d5ec116d06a3_refactor_backend_v2.py``). En Postgres la
   consulta NUNCA ve el slug de otra tienda: el 400 ``SLUG_ALREADY_IN_USE`` era
   inalcanzable y lo que salia era el 409 neutro del ``IntegrityError`` contra
   ``stores.slug UNIQUE``. En SQLite -donde corre toda la suite de
   integracion- no hay RLS, asi que ahi si se disparaba: cualquier test que
   afirmara el 400 habria estado verde por el motivo equivocado (§4 de
   CLAUDE.md). No habia ninguno en ninguna de las dos formas.
2. El mensaje literal era ``"El slug ya est? en uso"``: un ``?`` (0x3F) donde
   iba la ``a`` con tilde, resto de una conversion de codificacion con
   perdida, y el usuario final lo leia asi.

El pre-chequeo se borro. Lo que protegia -dos tiendas con el mismo slug- lo
sigue protegiendo la unica garantia que valia: el UNIQUE de ``stores.slug``
(``modules/stores/model.py``), que ``main.py`` traduce a 409 neutro (regla 20)
en su handler de ``IntegrityError`` -cuyo propio docstring ya decia "y bajo RLS
a veces ni siquiera ve la fila en conflicto"-. Con la cadena rota se fue
tambien el ``?``.

Este archivo afirma el comportamiento en SQLite, donde el pre-chequeo era lo
unico que se interponia; la version que prueba el camino REAL bajo RLS esta en
``tests/postgres/test_pg_slug_duplicado.py``.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

JsonDict = dict[str, Any]


@pytest.mark.asyncio
async def test_tomar_el_slug_de_otra_tienda_da_409_neutro(client: AsyncClient) -> None:
    _otra, token_otra = await register_and_login(
        client, slug="b315-ocupado", email="b315-a@test.com"
    )
    _propia, token = await register_and_login(
        client, slug="b315-propio", email="b315-b@test.com"
    )

    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"slug": "b315-ocupado"}
    )
    assert res.status_code == 409, res.text
    cuerpo = cast(JsonDict, res.json())
    assert cuerpo["error_code"] == "RESOURCE_CONFLICT", cuerpo
    # Sin el "?" de la cadena rota y sin nombrar la fila en conflicto.
    assert "?" not in cuerpo["message"], cuerpo
    assert "slug" not in cuerpo["message"].lower(), cuerpo

    # Se comprueba por la API y no con `test_session`: el UPDATE fallido deja la
    # sesion en PendingRollbackError hasta que la request termina, que es
    # justamente el estado que el 409 describe.
    ajena = await client.get("/stores/me", headers=auth_headers(token_otra))
    assert ajena.status_code == 200, ajena.text
    assert ajena.json()["slug"] == "b315-ocupado", "el slug ajeno quedo pisado"


@pytest.mark.asyncio
async def test_cambiar_el_slug_a_uno_libre_sigue_saliendo(client: AsyncClient) -> None:
    """Borrar el pre-chequeo no puede romper el caso normal."""
    _store, token = await register_and_login(
        client, slug="b315-libre", email="b315-c@test.com"
    )

    res = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"slug": "b315-nuevo"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["slug"] == "b315-nuevo"


@pytest.mark.asyncio
async def test_reenviar_el_propio_slug_no_es_un_conflicto(client: AsyncClient) -> None:
    """El formulario del panel manda el slug vigente en cada edicion."""
    _store, token = await register_and_login(
        client, slug="b315-mismo", email="b315-d@test.com"
    )

    res = await client.patch(
        "/stores/me",
        headers=auth_headers(token),
        json={"slug": "b315-mismo", "name": "Otro Nombre"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["slug"] == "b315-mismo"
    assert res.json()["name"] == "Otro Nombre"
