"""La unicidad case-insensitive del email la garantiza el indice, no el pre-chequeo.

Auditoria B3-05, 2026-09-17. Sintoma: el alta de admin por superadmin, el alta
de staff y la edicion de staff hacian "SELECT lower(email) y despues INSERT":
1) el par no es atomico, y en la carrera el superadmin atrapaba la
   ``IntegrityError`` y respondia 400 "Ya existe un usuario con ese email"
   en vez del 409 neutro de la regla 20 (``main.py``); 2) el pre-chequeo usaba
   ``scalar_one_or_none`` sin ``limit``: con dos filas heredadas que solo
   difieren en mayusculas, la propia guarda levantaba MultipleResultsFound
   (500) en los tres sitios.

La garantia determinista es la base: el email se guarda en minusculas
(``ck_users_email_lower``, F1-12) y la columna es unica, asi que dos
capitalizaciones son la misma fila; el indice funcional ``uq_users_email_lower``
(B3-01, migracion ``d2f4a6b8c0e2``) sigue como red previa. El pre-chequeo queda
solo como mensaje amable (regla 16), busca por IGUALDAD sobre la columna (bajo
RLS usa ``ix_users_email``; ``lower()`` recorria la tabla) y la carrera termina
en la base -> ``IntegrityError`` -> 409.

2026-09-24 (F1-12): los "duplicados heredados que solo difieren en mayusculas"
ya no pueden existir (la migracion del CHECK se detiene si los hay), asi que
los dos tests que los sembraban pasan a probar lo que queda: una capitalizacion
distinta de un email existente recibe el mensaje amable, no un 500.
"""

from collections.abc import Callable
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)
from tests.integration.test_superadmin import _bootstrap_global_admin

PASSWORD = "Password123!"


class _SinFilas:
    """Resultado vacio: simula que el SELECT del pre-chequeo no vio la fila."""

    def scalar_one_or_none(self) -> None:
        return None

    def first(self) -> None:
        return None

    def scalars(self) -> "_SinFilas":
        return self


def _es_pre_chequeo_de_email(statement: Any) -> bool:
    sql = " ".join(str(statement).split())
    return (
        sql.startswith("SELECT users.id FROM users WHERE users.email =")
        and "LIMIT" in sql
    )


def _simular_carrera(test_session: AsyncSession) -> Callable[[], None]:
    """Hace que el pre-chequeo por email "no vea" la fila existente.

    Es la carrera real: otra transaccion inserta el email entre el SELECT y el
    INSERT. Solo se intercepta el pre-chequeo (``SELECT users.id ... WHERE
    users.email = ... LIMIT``); el resto corre contra la base y el INSERT choca
    con el indice unico. Devuelve la funcion que restaura el ``execute`` real.
    """
    real_execute = test_session.execute

    async def execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
        if _es_pre_chequeo_de_email(statement):
            return _SinFilas()
        return await real_execute(statement, *args, **kwargs)

    test_session.execute = execute  # type: ignore[method-assign]

    def restaurar() -> None:
        test_session.execute = real_execute  # type: ignore[method-assign]

    return restaurar


def _staff_payload(email: str) -> dict[str, Any]:
    return {
        "display_name": "Doble",
        "first_name": "Doble",
        "last_name": "Identidad",
        "email": email,
        "service_ids": [],
    }


async def _contar(test_session: AsyncSession, email: str) -> int:
    filas = await test_session.execute(
        select(User.id).where(User.email == email.lower())
    )
    return len(filas.all())


async def _superadmin_con_tienda(
    client: AsyncClient, test_session: AsyncSession, slug: str
) -> tuple[dict[str, str], str]:
    headers = await _bootstrap_global_admin(
        client, test_session, slug=f"raiz-{slug}", email=f"root-{slug}@demo.com"
    )
    store = await client.post(
        "/superadmin/stores",
        headers=headers,
        json={"name": f"Tienda {slug}", "slug": slug},
    )
    assert store.status_code == 201, store.text
    return headers, cast(str, store.json()["public_id"])


@pytest.mark.asyncio
async def test_alta_de_admin_por_superadmin_en_carrera_da_409_neutro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers, store_pid = await _superadmin_con_tienda(
        client, test_session, "carrera-admin"
    )
    base = {"password": PASSWORD, "first_name": "Dup", "last_name": "Uno"}
    primero = await client.post(
        f"/superadmin/stores/{store_pid}/admins",
        headers=headers,
        json={**base, "email": "dup@demo.com"},
    )
    assert primero.status_code == 201, primero.text

    restaurar = _simular_carrera(test_session)
    colision = await client.post(
        f"/superadmin/stores/{store_pid}/admins",
        headers=headers,
        json={**base, "email": "DUP@demo.com"},
    )
    # Antes: 400 "Ya existe un usuario con ese email" (el repo tragaba la
    # IntegrityError). Ahora la base decide y main.py responde 409 neutro.
    assert colision.status_code == 409, colision.text
    assert colision.json()["error_code"] == "RESOURCE_CONFLICT"

    restaurar()
    await test_session.rollback()
    assert await _contar(test_session, "dup@demo.com") == 1


@pytest.mark.asyncio
async def test_alta_de_staff_en_carrera_da_409_neutro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="carrera-staff", email="dueno-carrera@test.com"
    )

    restaurar = _simular_carrera(test_session)
    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json=_staff_payload("DUENO-CARRERA@test.com"),
    )
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "RESOURCE_CONFLICT"

    restaurar()
    await test_session.rollback()
    assert await _contar(test_session, "dueno-carrera@test.com") == 1


@pytest.mark.asyncio
async def test_edicion_de_staff_en_carrera_da_409_neutro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="carrera-edicion", email="dueno-edicion@test.com"
    )
    alta = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json=_staff_payload("pro-edicion@test.com"),
    )
    assert alta.status_code == 201, alta.text
    staff_pid = alta.json()["public_id"]

    restaurar = _simular_carrera(test_session)
    res = await client.patch(
        f"/staff/{staff_pid}",
        headers=auth_headers(token),
        json={"email": "DUENO-EDICION@test.com"},
    )
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "RESOURCE_CONFLICT"

    restaurar()
    await test_session.rollback()
    assert await _contar(test_session, "dueno-edicion@test.com") == 1
    assert await _contar(test_session, "pro-edicion@test.com") == 1


@pytest.mark.asyncio
async def test_pre_chequeo_del_superadmin_ve_el_email_con_otra_capitalizacion(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers, store_pid = await _superadmin_con_tienda(
        client, test_session, "capitalizacion-admin"
    )
    base = {"password": PASSWORD, "first_name": "Dup", "last_name": "Tres"}
    primero = await client.post(
        f"/superadmin/stores/{store_pid}/admins",
        headers=headers,
        json={**base, "email": "viejo@demo.com"},
    )
    assert primero.status_code == 201, primero.text

    res = await client.post(
        f"/superadmin/stores/{store_pid}/admins",
        headers=headers,
        json={**base, "email": "Viejo@demo.com"},
    )
    # La igualdad sobre la columna normalizada la encuentra: mensaje amable.
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_pre_chequeo_de_staff_ve_el_email_con_otra_capitalizacion(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="capitalizacion-staff", email="dueno-capitalizacion@test.com"
    )
    existente = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json=_staff_payload("viejo@test.com"),
    )
    assert existente.status_code == 201, existente.text

    alta = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json=_staff_payload("Viejo@test.com"),
    )
    # El staff responde 422 (ValidationException) con el mensaje amable.
    assert alta.status_code == 422, alta.text

    nuevo = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json=_staff_payload("pro-capitalizacion@test.com"),
    )
    assert nuevo.status_code == 201, nuevo.text
    edicion = await client.patch(
        f"/staff/{nuevo.json()['public_id']}",
        headers=auth_headers(token),
        json={"email": "VIEJO@test.com"},
    )
    assert edicion.status_code == 422, edicion.text
