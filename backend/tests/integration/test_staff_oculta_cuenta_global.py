"""Las LECTURAS de ``/staff/`` tampoco muestran al profesional que es superadmin.

AUD2-B3-11, 2026-09-20. Sintoma: S-15 decidio que "la cuenta global no existe
para un admin de tienda", y lo aplico en ``GET /users/``, en ``revoke-user`` y
en las ESCRITURAS de ``/staff/`` (``_guardar_cuenta_vinculada`` da 404). Pero
``StaffRepository.get_all`` y ``get_by_id`` filtraban solo por ``store_id`` e
``is_active``: un profesional ascendido a superadmin conservaba su fila
``Staff`` y seguia apareciendo, con su email, en ``GET /staff/`` y en
``GET /staff/{id}``, mientras ``GET /users/`` no lo mostraba y
``PUT /staff/{id}`` sobre el daba 404. El panel se contradecia a si mismo.

Decision: "no existe" incluye las lecturas. El repositorio excluye a los
``Staff`` cuyo ``User`` es global salvo que quien consulta sea global, con el
mismo parametro ``include_global_admins`` que ya usa ``UserRepository``. Un
profesional ascendido a admin comun (no global) sigue a la vista: S-15 esconde
la cuenta global, no a los admins.

La escritura ya estaba cubierta en ``test_staff_no_toca_cuentas_admin.py``;
este archivo mira las lecturas.
"""

from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_staff_no_toca_cuentas_admin import _profesional_ascendido

JsonDict = dict[str, Any]


async def _ids_listados(client: AsyncClient, headers: dict[str, str]) -> set[str]:
    res = await client.get("/staff/", headers=headers)
    assert res.status_code == 200, res.text
    return {str(m["public_id"]) for m in cast(list[JsonDict], res.json())}


@pytest.mark.asyncio
async def test_el_staff_del_superadmin_no_aparece_en_las_lecturas_del_panel(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, staff_id, _ = await _profesional_ascendido(
        client, test_session, "b311-lectura", global_admin=True
    )
    headers = auth_headers(token)

    assert staff_id not in await _ids_listados(client, headers), (
        "GET /staff/ lista al profesional que es superadmin"
    )
    detalle = await client.get(f"/staff/{staff_id}", headers=headers)
    assert detalle.status_code == 404, detalle.text
    # Misma respuesta que las escrituras: no "prohibido", "no existe".
    assert "superadmin" not in detalle.text.lower(), detalle.text


@pytest.mark.asyncio
async def test_el_superadmin_si_ve_al_profesional_global(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    token, staff_id, _ = await _profesional_ascendido(
        client, test_session, "b311-global-ve", global_admin=True
    )
    dueno = (
        await test_session.execute(
            select(User).where(User.email == "b311-global-ve@test.com")
        )
    ).scalar_one()
    dueno.is_global_admin = True
    await test_session.commit()
    headers = auth_headers(token)

    assert staff_id in await _ids_listados(client, headers)
    detalle = await client.get(f"/staff/{staff_id}", headers=headers)
    assert detalle.status_code == 200, detalle.text
    assert detalle.json()["public_id"] == staff_id

    # Y puede editarlo y recargarlo (el reload posterior al update tambien
    # pasa por get_by_id: sin el flag daria 500 STAFF_RELOAD_FAILED).
    editar = await client.put(
        f"/staff/{staff_id}", headers=headers, json={"display_name": "Global Pro"}
    )
    assert editar.status_code == 200, editar.text
    assert editar.json()["display_name"] == "Global Pro"


@pytest.mark.asyncio
async def test_un_profesional_ascendido_a_admin_comun_sigue_a_la_vista(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """S-15 esconde la cuenta GLOBAL, no a los admins de la tienda."""
    token, staff_id, _ = await _profesional_ascendido(
        client, test_session, "b311-admin-comun", global_admin=False
    )
    headers = auth_headers(token)

    assert staff_id in await _ids_listados(client, headers)
    detalle = await client.get(f"/staff/{staff_id}", headers=headers)
    assert detalle.status_code == 200, detalle.text
