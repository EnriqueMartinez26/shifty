"""La unicidad case-insensitive del email la garantiza el indice, no el pre-chequeo.

Auditoria B3-05, 2026-09-17. Sintoma: el alta de admin por superadmin, el alta
de staff y la edicion de staff hacian "SELECT lower(email) y despues INSERT":
1) el par no es atomico, y en la carrera el superadmin atrapaba la
   ``IntegrityError`` y respondia 400 "Ya existe un usuario con ese email"
   en vez del 409 neutro de la regla 20 (``main.py``); 2) el pre-chequeo usaba
   ``scalar_one_or_none`` sin ``limit``: con dos filas heredadas que solo
   difieren en mayusculas, la propia guarda levantaba MultipleResultsFound
   (500) en los tres sitios.

La garantia determinista es el indice funcional ``uq_users_email_lower``
(B3-01, migracion ``d2f4a6b8c0e2``): el pre-chequeo queda solo como mensaje
amable (regla 16) y la carrera termina en la base -> ``IntegrityError`` -> 409.
"""

from collections.abc import Callable
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.users.model import User, UserRole
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


def _simular_carrera(test_session: AsyncSession) -> Callable[[], None]:
    """Hace que el pre-chequeo por lower(email) "no vea" la fila existente.

    Es la carrera real: otra transaccion inserta el email entre el SELECT y el
    INSERT. Solo se intercepta la consulta con ``lower(``; el resto corre
    contra la base y el INSERT choca con ``uq_users_email_lower``. Devuelve
    la funcion que restaura el ``execute`` real.
    """
    real_execute = test_session.execute

    async def execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
        if "lower(" in str(statement).lower():
            return _SinFilas()
        return await real_execute(statement, *args, **kwargs)

    test_session.execute = execute  # type: ignore[method-assign]

    def restaurar() -> None:
        test_session.execute = real_execute  # type: ignore[method-assign]

    return restaurar


async def _sembrar_duplicados_heredados(
    test_session: AsyncSession, store_id: str, email: str
) -> None:
    """Base anterior a la migracion: dos filas que solo difieren en mayusculas."""
    await test_session.execute(text("DROP INDEX uq_users_email_lower"))
    for variante in (email, email.upper()):
        test_session.add(
            User(
                email=variante,
                hashed_password=hash_password(PASSWORD),
                first_name="Dup",
                last_name="Heredado",
                role=UserRole.STAFF,
                store_id=store_id,
            )
        )
    await test_session.commit()


def _staff_payload(email: str) -> dict[str, Any]:
    return {
        "display_name": "Doble",
        "first_name": "Doble",
        "last_name": "Identidad",
        "email": email,
        "service_ids": [],
    }


async def _contar(test_session: AsyncSession, email: str) -> int:
    return (
        await test_session.execute(
            select(func.count()).where(func.lower(User.email) == email.lower())
        )
    ).scalar_one()


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
async def test_pre_chequeo_del_superadmin_no_da_500_con_duplicados_heredados(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    headers, store_pid = await _superadmin_con_tienda(
        client, test_session, "heredado-admin"
    )
    store_id = (
        await test_session.execute(
            select(User.store_id).where(User.email == "root-heredado-admin@demo.com")
        )
    ).scalar_one()
    await _sembrar_duplicados_heredados(test_session, store_id, "viejo@demo.com")

    res = await client.post(
        f"/superadmin/stores/{store_pid}/admins",
        headers=headers,
        json={
            "email": "Viejo@demo.com",
            "password": PASSWORD,
            "first_name": "Dup",
            "last_name": "Tres",
        },
    )
    # Antes: MultipleResultsFound -> 500. La guarda amable responde 400.
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_pre_chequeo_de_staff_no_da_500_con_duplicados_heredados(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    store_id, token = await register_and_login(
        client, slug="heredado-staff", email="dueno-heredado@test.com"
    )
    await _sembrar_duplicados_heredados(test_session, store_id, "viejo@test.com")

    alta = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json=_staff_payload("Viejo@test.com"),
    )
    # Antes: MultipleResultsFound -> 500. El staff responde 422 (ValidationException).
    assert alta.status_code == 422, alta.text

    nuevo = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json=_staff_payload("pro-heredado@test.com"),
    )
    assert nuevo.status_code == 201, nuevo.text
    edicion = await client.patch(
        f"/staff/{nuevo.json()['public_id']}",
        headers=auth_headers(token),
        json={"email": "VIEJO@test.com"},
    )
    assert edicion.status_code == 422, edicion.text
