"""El alta publica de clientes tambien normaliza el email (regla 16).

AUD2-B3-04, 2026-09-20. Sintoma: los tres caminos del panel bajaban el email a
minusculas antes de insertar; el cuarto --el que mas filas escribe-- no.
``get_or_create_client`` guardaba ``technical_email = email or ...`` tal como
llegaba y adoptaba con ``existing.email = email`` igual de crudo, y buscaba con
``User.email == email`` (comparacion exacta) en vez de ``func.lower(...)`` como
el login.

Consecuencia: el cliente reservaba una vez escribiendo ``Juan@Gmail.com`` y
quedaba esa fila; al volver desde otro telefono con ``juan@gmail.com`` la
busqueda exacta no encontraba nada, el codigo iba al INSERT y chocaba contra el
indice funcional ``uq_users_email_lower``. main.py responde 409 neutro y la
reserva legitima no se podia completar con ninguna variante de mayusculas.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.public_api.repository import PublicRepository
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon

TELEFONO = "+5491155551111"


async def _tienda(client: AsyncClient, slug: str) -> tuple[str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return (
        store,
        service,
        staff,
        dia.replace(hour=13, minute=0, second=0, microsecond=0),
    )


@pytest.mark.asyncio
async def test_la_reserva_publica_guarda_el_email_en_minusculas(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, service, staff, slot = await _tienda(client, "email-normalizado")

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": slot.isoformat(),
            "client_name": "Juan",
            "client_phone": TELEFONO,
            "accepts_terms": True,
            "client_email": "Juan@Gmail.COM",
            "idempotency_key": "email-normalizado-1",
        },
    )
    assert reserva.status_code == 201, reserva.text

    test_session.expire_all()
    fila = (
        await test_session.execute(
            select(User).where(
                User.phone == TELEFONO.lstrip("+"), User.role == UserRole.CLIENT
            )
        )
    ).scalar_one()
    assert fila.email == "juan@gmail.com", (
        "el alta publica guarda el email con la capitalizacion que llego"
    )


@pytest.mark.asyncio
async def test_volver_con_otra_capitalizacion_no_choca_contra_el_indice(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store_public_id, _service, _staff, _slot = await _tienda(client, "email-vuelta")
    store_id = await test_session.scalar(
        select(Store.id).where(Store.public_id == store_public_id)
    )
    assert store_id is not None

    repo = PublicRepository(test_session)
    primero = await repo.get_or_create_client(
        store_id=str(store_id),
        phone=TELEFONO.lstrip("+"),
        name="Juan",
        email="Juan@Gmail.COM",
    )
    await test_session.commit()
    assert primero.email == "juan@gmail.com"

    # Mismo telefono, el email con otra capitalizacion: tiene que ENCONTRAR la
    # fila (por telefono), no intentar un INSERT que el indice funcional
    # aborta. Desde el 2026-09-20 el flujo publico no adopta contacto ni busca
    # por email: el telefono es la unica llave de la ficha.
    segundo = await repo.get_or_create_client(
        store_id=str(store_id),
        phone=TELEFONO.lstrip("+"),
        name="Juan",
        email="JUAN@gmail.com",
    )
    await test_session.commit()
    assert segundo.id == primero.id
    assert segundo.email == "juan@gmail.com", (
        "la ficha existente conserva su email; el flujo publico no lo pisa"
    )
