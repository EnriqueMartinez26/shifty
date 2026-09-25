"""AUD2-B5-03, efecto colateral: la guarda de entrada no puede romper la salida.

``reject_control_chars`` se colgo de ``UserBase``, y de ``UserBase`` hereda
``UserResponse``. Con Pydantic v2 los ``field_validator`` corren tambien al
construir el modelo desde el ORM (``UserResponse.model_validate(user)``, que es
como el router arma TODAS sus respuestas), asi que una fila YA PERSISTIDA con un
caracter de control en ``first_name``/``last_name`` dejaba de poder serializarse:
``GET /users/`` entero se caia con ``ResponseValidationError`` -> 500, y con el
la lista de usuarios de la tienda.

Es el patron que la regla 19 no quiere: cerrar la puerta de entrada dejo el
sistema sin poder LEER lo que ya habia entrado antes de que la puerta existiera.
Esas filas existen: la guarda es nueva (2026-09-20) y la columna acepto texto
libre desde siempre. Y el 500 es opaco (regla 20): el dueno ve "error del
servidor" en la pantalla de usuarios y nadie puede decir cual es la fila mala.

La guarda vive ahora en los schemas de ENTRADA (``UserCreate`` y ``UserUpdate``);
``UserResponse`` la hereda ya no. La limpieza de los exportadores (el mismo
commit) sigue siendo la segunda capa, y es la que hace que esa fila sucia no
llegue a la planilla.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

SLUG = "aud2b503sucia"
EMAIL = "aud2b503sucia@test.com"
# NUL, bidi override y zero-width: los mismos que rechaza la entrada.
NOMBRE_SUCIO = "Ana\x00"
APELLIDO_SUCIO = "P‮rez​"


async def _sembrar_fila_sucia(session: AsyncSession, store_id: str) -> tuple[str, str]:
    """Inserta por el ORM, salteando los schemas: simula la fila legacy."""
    sucio = User(
        email="legacy-sucio@test.com",
        hashed_password="no-se-loguea",
        first_name=NOMBRE_SUCIO,
        last_name=APELLIDO_SUCIO,
        role=UserRole.STAFF,
        store_id=store_id,
    )
    session.add(sucio)
    await session.commit()
    await session.refresh(sucio)
    return str(sucio.public_id), str(sucio.email)


@pytest.mark.asyncio
async def test_una_fila_legacy_sucia_no_tumba_el_listado_de_usuarios(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(client, slug=SLUG, email=EMAIL)
    store = (
        await test_session.execute(select(Store).where(Store.slug == SLUG))
    ).scalar_one()
    public_id, email_sucio = await _sembrar_fila_sucia(test_session, store.id)

    # Con el validador en UserBase: ResponseValidationError -> 500.
    listado = await client.get("/users/", headers=auth_headers(token))
    assert listado.status_code == 200, listado.text

    emails = [item["email"] for item in listado.json()]
    assert email_sucio in emails, "la fila sucia tiene que poder leerse, no desaparecer"

    # El detalle de esa misma fila tambien se sirve.
    detalle = await client.get(f"/users/{public_id}", headers=auth_headers(token))
    assert detalle.status_code == 200, detalle.text
    assert detalle.json()["first_name"] == NOMBRE_SUCIO


@pytest.mark.asyncio
async def test_el_alta_por_la_api_sigue_rechazando_el_texto_hostil(
    client: AsyncClient,
) -> None:
    """La puerta de entrada no se aflojo al mover el validador."""
    _, token = await register_and_login(
        client, slug="aud2b503alta", email="aud2b503alta@test.com"
    )
    res = await client.post(
        "/users/",
        headers=auth_headers(token),
        json={
            "email": "nueva-sucia@test.com",
            "password": "Contrasena-Larga-9",
            "first_name": NOMBRE_SUCIO,
            "last_name": "Perez",
            "role": "staff",
        },
    )
    assert res.status_code == 422, res.text
