"""La auditoria de turnos y bloqueos se escribe con su tienda y se puede leer.

2026-09-18, hallazgo B5-12: los 11 puntos de ``uow.audit.log`` (appointments
y appointment_blocks) grababan filas que ningun endpoint leia; el unico lector
(``superadmin``) filtraba ``context == "superadmin"`` y las descartaba. B3-11
agrego ``audit_logs.store_id`` y relleno las filas viejas, pero
``AuditRepository.log`` seguia escribiendo ``store_id`` NULL en las nuevas.

Decision (OK global del usuario, sugerencia del brief): exponer un endpoint
minimo de solo lectura, en vez de purgar. ``GET /reports/audit-logs``:
- acotado a la tienda del usuario con ``AuditLog.store_id`` en SQL. La tabla
  esta FUERA de RLS, asi que ese filtro es LA guarda (test de dos tiendas);
- solo turnos y bloqueos (``Appointment`` / ``AppointmentBlock``), no las
  acciones del superadmin sobre la tienda;
- paginado con ``limit``/``offset`` acotados por los dos lados (regla 9),
  ``created_at desc``, filtrable por ``resource_id``;
- admin de tienda y superadmin (``STORE_MANAGERS``): el modulo de turnos no
  restringe al profesional a sus propios turnos, asi que se toma la variante
  de admins.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.audit.model import AuditLog
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_aislamiento_multitenant import _montar, _turno
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)


async def _store_id(session: AsyncSession, public_id: str) -> str:
    store = (
        await session.execute(select(Store).where(Store.public_id == public_id))
    ).scalar_one()
    return str(store.id)


@pytest.mark.asyncio
async def test_una_transicion_de_turno_deja_la_fila_con_su_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda = await _montar(client, slug="b512-escritura", email="b512-w@test.com")
    turno = await _turno(client, tienda, hora=10, clave="b512-escritura-1")
    confirmado = await client.patch(
        f"/appointments/{turno}/confirm", headers=auth_headers(tienda.token)
    )
    assert confirmado.status_code == 200, confirmado.text

    filas = (
        await test_session.execute(
            select(AuditLog.action, AuditLog.store_id).where(
                AuditLog.resource_id == turno
            )
        )
    ).all()
    esperado = await _store_id(test_session, tienda.store)
    assert sorted(a for a, _ in filas) == ["create", "status_change"]
    assert {s for _, s in filas} == {esperado}


@pytest.mark.asyncio
async def test_cada_tienda_lee_solo_su_auditoria_de_turnos(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    a = await _montar(client, slug="b512-a", email="b512-a@test.com")
    b = await _montar(client, slug="b512-b", email="b512-b@test.com")
    turno_a1 = await _turno(client, a, hora=10, clave="b512-lectura-a1")
    turno_a2 = await _turno(client, a, hora=11, clave="b512-lectura-a2")
    turno_b = await _turno(client, b, hora=10, clave="b512-lectura-b1")
    confirmado = await client.patch(
        f"/appointments/{turno_a1}/confirm", headers=auth_headers(a.token)
    )
    assert confirmado.status_code == 200, confirmado.text
    # Una accion del superadmin sobre la tienda A: no es auditoria de turnos.
    test_session.add(
        AuditLog(
            resource_type="Store",
            resource_id=a.store,
            store_id=await _store_id(test_session, a.store),
            action="update",
            context="superadmin",
        )
    )
    await test_session.commit()

    res = await client.get("/reports/audit-logs", headers=auth_headers(a.token))
    assert res.status_code == 200, res.text
    items = res.json()
    ids = [i["resource_id"] for i in items]
    assert turno_b not in ids
    assert a.store not in ids
    assert sorted(ids) == sorted([turno_a1, turno_a1, turno_a2])
    # Mas reciente primero: la confirmacion de a1 fue lo ultimo.
    assert (items[0]["resource_id"], items[0]["action"]) == (turno_a1, "status_change")
    assert set(items[0]) == {
        "id",
        "created_at",
        "actor_email",
        "resource_type",
        "resource_id",
        "action",
        "payload_before",
        "payload_after",
    }

    solo_a2 = await client.get(
        "/reports/audit-logs",
        params={"resource_id": turno_a2},
        headers=auth_headers(a.token),
    )
    assert [i["resource_id"] for i in solo_a2.json()] == [turno_a2]

    pagina = await client.get(
        "/reports/audit-logs",
        params={"limit": 1, "offset": 1},
        headers=auth_headers(a.token),
    )
    assert [i["resource_id"] for i in pagina.json()] == [ids[1]]

    res_b = await client.get("/reports/audit-logs", headers=auth_headers(b.token))
    assert [i["resource_id"] for i in res_b.json()] == [turno_b]

    # El superadmin tambien lee solo su tienda (sin consolidado, como B5-02).
    admin_b = (
        await test_session.execute(select(User).where(User.email == "b512-b@test.com"))
    ).scalar_one()
    admin_b.is_global_admin = True
    await test_session.commit()
    res_global = await client.get("/reports/audit-logs", headers=auth_headers(b.token))
    assert [i["resource_id"] for i in res_global.json()] == [turno_b]


@pytest.mark.asyncio
async def test_el_profesional_no_lee_la_auditoria(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda = await _montar(client, slug="b512-pro", email="b512-pro@test.com")
    usuario = (
        await test_session.execute(
            select(User).where(User.email == "b512-pro@test.com")
        )
    ).scalar_one()
    usuario.role = UserRole.STAFF
    await test_session.commit()
    res = await client.get("/reports/audit-logs", headers=auth_headers(tienda.token))
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"offset": 10_001},
        {"resource_id": "no valido!"},
    ],
)
async def test_los_parametros_tienen_cota(
    client: AsyncClient, params: dict[str, str | int]
) -> None:
    tienda = await _montar(client, slug="b512-cotas", email="b512-cotas@test.com")
    res = await client.get(
        "/reports/audit-logs", params=params, headers=auth_headers(tienda.token)
    )
    assert res.status_code == 422, res.text
