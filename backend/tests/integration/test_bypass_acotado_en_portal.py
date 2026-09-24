"""Cada endpoint del portal abre y cierra el bypass de RLS con ``tenant_bypass``.

Seguimiento S-09 (2026-09-18) de B3-13. Los endpoints del portal (reserva,
"mis turnos", lista de espera) y la disponibilidad anonima del panel hacian
``set_tenant_context(None, True)`` + apply a la entrada y en el ``finally``
solo ``set_tenant_context(None, False)``, sin re-aplicarlo. Ahora usan
``tenant_bypass(db)``.

Que mide este test y que NO: la fixture de integracion usa un ``AsyncSession``
comun, no ``TenantSession``, asi que aca no se reproduce la fuga real (que
depende de que ``TenantSession.commit()`` re-aplique el contexto vigente y
deje la conexion con ``app.is_global_admin = true``). Lo que se mide es que
cada endpoint pase por ``tenant_bypass``: se espia
``core.database._apply_tenant_context`` y se exige que se aplique el bypass y
que lo ultimo aplicado sea el contexto sin bypass. Con el codigo viejo el
espia no registraba nada, porque los routers importaban el nombre y llamaban
su propia referencia.

La fuga en la conexion real se prueba contra Postgres en
tests/postgres/test_pg_bypass_de_tenant.py. La guarda estatica esta en
tests/unit/test_bypass_de_tenant.py.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient

import core.database as database
from core.database import _current_store_id, _is_global_admin
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)


def _espiar_aplicaciones(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, bool]]:
    aplicados: list[tuple[Any, bool]] = []
    original = database._apply_tenant_context

    async def registrar(session: Any) -> None:
        aplicados.append((_current_store_id.get(), _is_global_admin.get()))
        await original(session)

    monkeypatch.setattr(database, "_apply_tenant_context", registrar)
    return aplicados


@pytest.mark.asyncio
async def test_los_endpoints_del_portal_bajan_el_bypass_en_la_conexion(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, token = await register_and_login(
        client, slug="bypass-portal", email="bypass-portal@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)

    pedidos: list[tuple[str, str, dict[str, str] | None, dict[str, object] | None]] = [
        ("GET", "/public/stores/bypass-portal", None, None),
        ("GET", "/public/services", {"store_public_id": store}, None),
        (
            "GET",
            "/public/availability",
            {
                "store_public_id": store,
                "service_id": service,
                "date": slot.date().isoformat(),
            },
            None,
        ),
        (
            "GET",
            "/appointments/availability",
            {"service_id": service, "date": slot.date().isoformat()},
            None,
        ),
        (
            "POST",
            "/public/waitlist",
            None,
            {
                "store_public_id": store,
                "service_id": service,
                "window_starts_at": (slot - timedelta(hours=2)).isoformat(),
                "window_ends_at": (slot + timedelta(hours=2)).isoformat(),
                "client_name": "Bypass",
                "client_phone": "+5491155551001",
            },
        ),
        (
            "POST",
            "/public/appointments",
            None,
            {
                "store_public_id": store,
                "service_id": service,
                "staff_id": staff,
                "starts_at": slot.isoformat(),
                "client_name": "Bypass",
                "client_phone": "+5491155551002",
                "accepts_terms": True,
                "idempotency_key": "bypass-portal-0001",
            },
        ),
    ]
    for metodo, ruta, params, cuerpo in pedidos:
        aplicados = _espiar_aplicaciones(monkeypatch)
        res = await client.request(metodo, ruta, params=params, json=cuerpo)
        monkeypatch.undo()
        assert res.status_code in (200, 201), (ruta, res.text)
        assert (None, True) in aplicados, (ruta, aplicados)
        assert aplicados[-1] == (None, False), (
            f"{ruta} dejo la conexion con el bypass puesto: {aplicados}"
        )
