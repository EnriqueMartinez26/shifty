"""``pending_confirmations`` cuenta lo que el dueno todavia puede confirmar.

2026-09-20, hallazgo AUD2-B5-11: ``count_pending()`` contaba TODOS los turnos
``pending`` de la tienda, sin ninguna cota de fecha, mientras el resto de los
contadores del panel si acotan. Un turno pendiente cuya fecha ya paso no cambia
de estado solo —el grafo lo lleva a ``absent``/``completed`` por accion del
staff—, asi que el contador es monotono creciente. Sintoma: a los seis meses el
dueno ve "137 confirmaciones pendientes" donde hay dos reales, el numero deja
de disparar accion y se vuelve ruido.

Decision: son los pendientes FUTUROS, el mismo horizonte que ya usa la lista de
proximos turnos del panel (``upcoming(now, ...)``). Los pendientes vencidos que
el dueno nunca cerro son otro problema y, si se quieren ver, merecen su propio
contador.

Reloj congelado: miercoles 2026-09-16 a las 15:00 ART, como el resto del panel.
"""

from datetime import time, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import core.utils
from modules.appointments.model import AppointmentStatus
from modules.services.model import Service
from modules.staff.model import Staff
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_panel_en_service import HOY_LOCAL, _RelojCongelado, _turno


@pytest.mark.asyncio
async def test_un_pendiente_de_hace_dos_meses_no_sigue_contando(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core.utils, "datetime", _RelojCongelado)
    store_public_id, token = await register_and_login(
        client, slug="aud2b511", email="aud2b511@test.com"
    )
    servicio_public_id = await create_service(client, token)
    staff_public_id = await create_staff(
        client, token, servicio_public_id, email="pro-aud2b511@test.com"
    )
    store = (
        await test_session.execute(
            select(Store).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    servicio = (
        await test_session.execute(
            select(Service).where(Service.public_id == servicio_public_id)
        )
    ).scalar_one()
    staff = (
        await test_session.execute(select(Staff).where(Staff.id == staff_public_id))
    ).scalar_one()
    cliente = User(
        email="cliente-aud2b511@test.com",
        hashed_password="no-se-loguea",
        first_name="Ana",
        last_name="Cliente",
        role=UserRole.CLIENT,
        store_id=store.id,
    )
    test_session.add(cliente)
    await test_session.commit()

    async def pendiente(clave: str, dias: int, hora: time) -> None:
        await _turno(
            test_session,
            store=store,
            cliente=cliente,
            servicio=servicio,
            staff=staff,
            dia=HOY_LOCAL + timedelta(days=dias),
            hora=hora,
            estado=AppointmentStatus.PENDING,
            clave=clave,
        )

    await pendiente("aud2b511-viejo", -60, time(10, 0))
    await pendiente("aud2b511-ayer", -1, time(10, 0))
    await pendiente("aud2b511-hoy-pasado", 0, time(10, 0))  # 10:00, ya pasaron
    await pendiente("aud2b511-hoy-futuro", 0, time(16, 0))
    await pendiente("aud2b511-manana", 1, time(10, 0))

    res = await client.get("/dashboard/summary", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    # Solo los dos que el dueno todavia puede confirmar. Antes eran cinco y el
    # numero nunca bajaba.
    assert res.json()["stats"]["pending_confirmations"] == 2
