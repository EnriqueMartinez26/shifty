"""``PATCH /staff/{id}/services`` valida la lista como el alta: patron y tope.

Auditoria B3-14, 2026-09-17. Sintoma: el endpoint declaraba
``service_ids: list[str]``, sin ``pattern`` ni ``max_length``, mientras que el
alta ya usaba ``list[PublicId]`` con ``max_length=100``
(``staff/schemas.py``). Un array de 100.000 strings arbitrarios llegaba tal
cual al ``Service.public_id.in_(...)`` del repositorio y al ``set()`` que
compara los tamanos.

El body sigue siendo un array JSON crudo: el contrato con el panel no cambia.
"""

import pytest
from httpx import AsyncClient

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


async def _tienda_con_personal(client: AsyncClient) -> tuple[str, str, str]:
    _, token = await register_and_login(
        client, slug="staff-servicios", email="staff-servicios@test.com"
    )
    servicio = await create_service(client, token)
    profesional = await create_staff(client, token, servicio)
    return token, profesional, servicio


@pytest.mark.asyncio
async def test_la_lista_de_servicios_tiene_tope(client: AsyncClient) -> None:
    token, staff_id, servicio_id = await _tienda_con_personal(client)

    desborde = await client.patch(
        f"/staff/{staff_id}/services",
        headers=auth_headers(token),
        json=[servicio_id] * 101,
    )
    assert desborde.status_code == 422, desborde.text


@pytest.mark.asyncio
async def test_un_id_que_no_es_public_id_se_rechaza_antes_de_la_consulta(
    client: AsyncClient,
) -> None:
    token, staff_id, _ = await _tienda_con_personal(client)

    for basura in ("' OR 1=1 --", "a" * 65, "con espacio", "\u202eid"):
        res = await client.patch(
            f"/staff/{staff_id}/services",
            headers=auth_headers(token),
            json=[basura],
        )
        assert res.status_code == 422, f"{basura!r} paso la validacion: {res.text}"
        # Hoy tambien daba 422, pero DESPUES de la consulta: era el ValueError
        # del repositorio ("no existen o no pertenecen al negocio"). Tiene que
        # cortarlo el schema, antes de llegar al in_().
        assert "no existen" not in res.text, (
            f"{basura!r} llego hasta la consulta: el schema no lo freno"
        )


@pytest.mark.asyncio
async def test_el_body_sigue_siendo_un_array_crudo(client: AsyncClient) -> None:
    """El contrato con el front no cambia: la lista NO va envuelta en objeto."""
    token, staff_id, servicio_id = await _tienda_con_personal(client)

    ok = await client.patch(
        f"/staff/{staff_id}/services",
        headers=auth_headers(token),
        json=[servicio_id],
    )
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"message": "Servicios actualizados correctamente"}

    vacia = await client.patch(
        f"/staff/{staff_id}/services", headers=auth_headers(token), json=[]
    )
    assert vacia.status_code == 200, vacia.text
