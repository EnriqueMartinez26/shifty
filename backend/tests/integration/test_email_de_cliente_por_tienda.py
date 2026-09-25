"""PV-01: el email de un cliente es unico POR TIENDA; el del personal, global.

2026-09-25 (auditoria de privacidad, PV-01). Sintoma: ``users.email`` era
unico en toda la plataforma. Quien reservaba en la tienda A con su email
recibia 409 ``RESOURCE_CONFLICT`` al reservar en la tienda B con el mismo
email, por el portal y por el alta del panel. El mismo 409 era un oraculo
publico: cualquiera, sin cuenta, sabia si un email existia en Shifty (cliente
de otra tienda o cuenta de administrador).

Decision del dueno (2026-09-25): un cliente usa el mismo email en todas las
tiendas que quiera. Los clientes no inician sesion (el portal es telefono +
OTP), asi que su email solo tiene que ser unico dentro de su tienda. El
personal, los admins y el superadmin entran por email: el suyo sigue unico
entre las cuentas que pueden iniciar sesion. Un cliente y un profesional
pueden compartir email (el barbero que es cliente de otra tienda), asi que el
login, el olvido de clave y los pre-chequeos de alta filtran ``role <>
'client'``: ``scalar_one_or_none`` nunca ve dos filas (regla 16).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_superadmin import _bootstrap_global_admin

EMAIL = "ana@example.com"
PASSWORD = "Password123!"


class Tienda:
    def __init__(
        self, store: str, token: str, service: str, staff: str, slot: datetime
    ) -> None:
        self.store = store
        self.token = token
        self.service = service
        self.staff = staff
        self.slot = slot


async def _tienda(client: AsyncClient, slug: str) -> Tienda:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)
    return Tienda(store, token, service, staff, slot)


async def _reserva_publica(
    client: AsyncClient,
    tienda: Tienda,
    *,
    phone: str,
    email: str,
    key: str,
    hora: int = 0,
) -> Response:
    return await client.post(
        "/public/appointments",
        json={
            "store_public_id": tienda.store,
            "service_id": tienda.service,
            "staff_id": tienda.staff,
            "starts_at": (tienda.slot + timedelta(hours=hora)).isoformat(),
            "client_name": "Ana Cliente",
            "client_phone": phone,
            "accepts_terms": True,
            "client_email": email,
            "idempotency_key": key,
        },
    )


async def _reserva_del_panel(
    client: AsyncClient,
    tienda: Tienda,
    *,
    phone: str,
    email: str,
    key: str,
) -> Response:
    return await client.post(
        "/appointments/",
        headers=auth_headers(tienda.token),
        json={
            "service_id": tienda.service,
            "staff_id": tienda.staff,
            "starts_at": tienda.slot.isoformat(),
            "client_name": "Ana Cliente",
            "client_phone": phone,
            "client_email": email,
            "idempotency_key": key,
        },
    )


async def _store_id(session: AsyncSession, public_id: str) -> str:
    return str(
        (
            await session.execute(select(Store.id).where(Store.public_id == public_id))
        ).scalar_one()
    )


async def _filas(session: AsyncSession, email: str) -> list[User]:
    session.expire_all()
    return list(
        (await session.execute(select(User).where(User.email == email))).scalars()
    )


@pytest.fixture(autouse=True)
def _sin_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())


# ------------------------------------------------ el mismo email en dos tiendas
@pytest.mark.asyncio
async def test_reserva_publica_con_el_mismo_email_en_dos_tiendas(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    alfa = await _tienda(client, "pv01-pub-alfa")
    beta = await _tienda(client, "pv01-pub-beta")

    en_alfa = await _reserva_publica(
        client, alfa, phone="+5491155550301", email=EMAIL, key="pv01-pub-a"
    )
    assert en_alfa.status_code == 201, en_alfa.text
    # Otro telefono y el MISMO email en otra tienda: antes 409 (oraculo PV-01).
    en_beta = await _reserva_publica(
        client, beta, phone="+5491155550302", email="Ana@Example.com", key="pv01-pub-b"
    )
    assert en_beta.status_code == 201, en_beta.text

    filas = await _filas(test_session, EMAIL)
    assert sorted(f.store_id for f in filas) == sorted(
        [
            await _store_id(test_session, alfa.store),
            await _store_id(test_session, beta.store),
        ]
    )
    assert all(f.role == UserRole.CLIENT for f in filas)
    assert len({f.id for f in filas}) == 2


@pytest.mark.asyncio
async def test_reserva_del_panel_con_el_mismo_email_en_dos_tiendas(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    alfa = await _tienda(client, "pv01-panel-alfa")
    beta = await _tienda(client, "pv01-panel-beta")

    en_alfa = await _reserva_del_panel(
        client, alfa, phone="+5491155550311", email=EMAIL, key="pv01-panel-a"
    )
    assert en_alfa.status_code == 201, en_alfa.text
    en_beta = await _reserva_del_panel(
        client, beta, phone="+5491155550311", email=EMAIL, key="pv01-panel-b"
    )
    assert en_beta.status_code == 201, en_beta.text

    filas = await _filas(test_session, EMAIL)
    assert len(filas) == 2
    assert len({f.store_id for f in filas}) == 2


@pytest.mark.asyncio
async def test_lista_de_espera_con_el_email_de_un_cliente_de_otra_tienda(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    alfa = await _tienda(client, "pv01-espera-alfa")
    beta = await _tienda(client, "pv01-espera-beta")
    reserva = await _reserva_publica(
        client, alfa, phone="+5491155550321", email=EMAIL, key="pv01-espera-a"
    )
    assert reserva.status_code == 201, reserva.text

    alta = await client.post(
        "/public/waitlist",
        json={
            "store_public_id": beta.store,
            "service_id": beta.service,
            "window_starts_at": (beta.slot - timedelta(hours=3)).isoformat(),
            "window_ends_at": (beta.slot + timedelta(hours=3)).isoformat(),
            "client_name": "Ana Espera",
            "client_phone": "+5491155550322",
            "client_email": EMAIL,
        },
    )
    assert alta.status_code == 201, alta.text
    assert len(await _filas(test_session, EMAIL)) == 2


# ------------------------------------------------------ dentro de UNA tienda
@pytest.mark.asyncio
async def test_mismo_telefono_y_email_en_la_misma_tienda_es_un_solo_cliente(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    alfa = await _tienda(client, "pv01-una-alfa")
    primera = await _reserva_publica(
        client, alfa, phone="+5491155550331", email=EMAIL, key="pv01-una-1"
    )
    assert primera.status_code == 201, primera.text
    segunda = await _reserva_publica(
        client, alfa, phone="+5491155550331", email=EMAIL, key="pv01-una-2", hora=1
    )
    assert segunda.status_code == 201, segunda.text
    assert len(await _filas(test_session, EMAIL)) == 1


@pytest.mark.asyncio
async def test_otro_telefono_con_el_email_de_un_cliente_de_la_tienda_es_409_neutro(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    alfa = await _tienda(client, "pv01-dup-alfa")
    primera = await _reserva_publica(
        client, alfa, phone="+5491155550341", email=EMAIL, key="pv01-dup-1"
    )
    assert primera.status_code == 201, primera.text
    # Dentro de la tienda el email sigue siendo de UN cliente: el telefono
    # nuevo no adopta la ficha ("un telefono sin OTP no es de nadie").
    segunda = await _reserva_publica(
        client, alfa, phone="+5491155550342", email=EMAIL, key="pv01-dup-2", hora=1
    )
    assert segunda.status_code == 409, segunda.text
    cuerpo = segunda.json()
    assert cuerpo["error_code"] == "RESOURCE_CONFLICT"
    assert "email" not in str(cuerpo.get("message", "")).lower()
    assert len(await _filas(test_session, EMAIL)) == 1


# ------------------------------------------------ personal: unico global
@pytest.mark.asyncio
async def test_el_email_del_personal_sigue_unico_entre_tiendas(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    alfa = await _tienda(client, "pv01-staff-alfa")
    beta = await _tienda(client, "pv01-staff-beta")
    service_beta = beta.service

    res = await client.post(
        "/staff/",
        headers=auth_headers(beta.token),
        json={
            "display_name": "Duplicado",
            "first_name": "Dup",
            "last_name": "Licado",
            "email": "pro-pv01-staff-alfa@example.com",
            "service_ids": [service_beta],
        },
    )
    # SQLite no aplica RLS: el pre-chequeo ve la fila de alfa (422). En
    # Postgres no la ve y decide el indice unico (409). Nunca 201.
    assert res.status_code in (409, 422), res.text
    filas = await _filas(test_session, "pro-pv01-staff-alfa@example.com")
    assert [f.store_id for f in filas] == [await _store_id(test_session, alfa.store)]


@pytest.mark.asyncio
async def test_un_profesional_puede_tener_el_email_de_un_cliente(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    alfa = await _tienda(client, "pv01-barbero-alfa")
    beta = await _tienda(client, "pv01-barbero-beta")
    # Es cliente de alfa...
    reserva = await _reserva_publica(
        client, alfa, phone="+5491155550351", email=EMAIL, key="pv01-barbero-a"
    )
    assert reserva.status_code == 201, reserva.text
    # ...y profesional de beta: el pre-chequeo del alta no cuenta clientes.
    alta = await client.post(
        "/staff/",
        headers=auth_headers(beta.token),
        json={
            "display_name": "Ana Barbera",
            "first_name": "Ana",
            "last_name": "Barbera",
            "email": EMAIL,
            "service_ids": [beta.service],
        },
    )
    assert alta.status_code == 201, alta.text

    roles = sorted(
        str(getattr(f.role, "value", f.role)) for f in await _filas(test_session, EMAIL)
    )
    assert roles == ["client", "staff"]


@pytest.mark.asyncio
async def test_superadmin_da_de_alta_un_admin_con_el_email_de_un_cliente(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    alfa = await _tienda(client, "pv01-admin-alfa")
    reserva = await _reserva_publica(
        client, alfa, phone="+5491155550361", email=EMAIL, key="pv01-admin-a"
    )
    assert reserva.status_code == 201, reserva.text

    headers = await _bootstrap_global_admin(
        client, test_session, slug="pv01-raiz", email="raiz-pv01@demo.com"
    )
    store = await client.post(
        "/superadmin/stores",
        headers=headers,
        json={"name": "Tienda PV01", "slug": "pv01-nueva"},
    )
    assert store.status_code == 201, store.text
    alta = await client.post(
        f"/superadmin/stores/{store.json()['public_id']}/admins",
        headers=headers,
        json={
            "email": EMAIL,
            "password": PASSWORD,
            "first_name": "Ana",
            "last_name": "Duena",
        },
    )
    assert alta.status_code == 201, alta.text

    # Un segundo admin con ese email en otra tienda sigue rechazado.
    otra = await client.post(
        "/superadmin/stores",
        headers=headers,
        json={"name": "Tienda PV01 bis", "slug": "pv01-nueva-bis"},
    )
    assert otra.status_code == 201, otra.text
    repetido = await client.post(
        f"/superadmin/stores/{otra.json()['public_id']}/admins",
        headers=headers,
        json={
            "email": EMAIL,
            "password": PASSWORD,
            "first_name": "Ana",
            "last_name": "Otra",
        },
    )
    assert repetido.status_code in (400, 409), repetido.text


# ------------------------------------------------ login sin ambiguedad
@pytest.mark.asyncio
async def test_login_y_olvido_de_clave_no_ven_al_cliente_con_el_mismo_email(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    alfa = await _tienda(client, "pv01-login-alfa")
    beta = await _tienda(client, "pv01-login-beta")
    email_del_dueno = "pv01-login-alfa@example.com"

    # El dueno de alfa reserva como cliente en beta con su email de login.
    reserva = await _reserva_publica(
        client, beta, phone="+5491155550371", email=email_del_dueno, key="pv01-login"
    )
    assert reserva.status_code == 201, reserva.text
    assert len(await _filas(test_session, email_del_dueno)) == 2

    login = await client.post(
        "/auth/login", json={"email": email_del_dueno.upper(), "password": PASSWORD}
    )
    assert login.status_code == 200, login.text

    olvido = await client.post("/auth/forgot-password", json={"email": email_del_dueno})
    assert olvido.status_code == 200, olvido.text
    filas = {
        str(getattr(f.role, "value", f.role)): f
        for f in await _filas(test_session, email_del_dueno)
    }
    assert filas["admin"].password_reset_token_hash is not None
    assert filas["client"].password_reset_token_hash is None
    assert filas["admin"].store_id == await _store_id(test_session, alfa.store)


# ------------------------------------------------ aislamiento entre tiendas
@pytest.mark.asyncio
async def test_clientes_con_el_mismo_email_no_comparten_datos(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    from modules.otp.service import OtpService
    from modules.public_api.repository import PublicRepository

    alfa = await _tienda(client, "pv01-aisla-alfa")
    beta = await _tienda(client, "pv01-aisla-beta")
    reserva = await _reserva_publica(
        client, alfa, phone="+5491155550381", email=EMAIL, key="pv01-aisla-a"
    )
    assert reserva.status_code == 201, reserva.text
    otra = await _reserva_publica(
        client, beta, phone="+5491155550382", email=EMAIL, key="pv01-aisla-b"
    )
    assert otra.status_code == 201, otra.text
    alfa_id = await _store_id(test_session, alfa.store)
    beta_id = await _store_id(test_session, beta.store)

    # Historial: el de beta no cuenta los turnos de alfa aunque el email sea
    # el mismo (se busca por tienda + telefono, nunca por email).
    from sqlalchemy import update

    from modules.appointments.model import Appointment

    await test_session.execute(
        update(Appointment)
        .where(Appointment.store_id == alfa_id)
        .values(status="completed")
    )
    await test_session.commit()
    repo = PublicRepository(test_session)
    historial_beta = await repo.get_client_history(beta_id, "5491155550382")
    assert (historial_beta.completed, historial_beta.absent) == (0, 0)
    historial_alfa = await repo.get_client_history(alfa_id, "5491155550381")
    assert historial_alfa.completed == 1

    # OTP: el telefono de alfa no tiene ficha en beta, asi que beta no manda
    # el codigo al email de la ficha de alfa (el contacto es por tienda).
    otp: Any = OtpService(test_session)
    assert await otp._registered_client_email(beta_id, "+5491155550381") is None
    assert await otp._registered_client_email(alfa_id, "+5491155550381") == EMAIL

    # Panel: el listado de clientes de beta trae solo su ficha.
    clientes = await client.get(
        "/users/", headers=auth_headers(beta.token), params={"email": EMAIL}
    )
    assert clientes.status_code == 200, clientes.text
    assert [c["phone"] for c in clientes.json()] == ["5491155550382"]
