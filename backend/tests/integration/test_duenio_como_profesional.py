"""El dueno tambien atiende: su cuenta de admin se agrega como profesional.

2026-10-08, decision de Mateo: el dueno de la tienda (la cuenta admin) tiene
que poder figurar y recibir reservas como profesional CON SU NOMBRE. Antes
la unica forma era ``POST /staff/``, que crea un usuario de login nuevo: con
su email ya usado (unico global, regla 16) tenia que inventar otro.

``POST /staff/me`` crea la ficha de profesional de la cuenta que llama
(``Staff.id == User.id``, como cualquier persona del personal): sin cuenta
nueva, sin email repetido, sin cambiar su rol. Quitarse de la agenda
(``DELETE /staff/{su id}``) no le desactiva el login ni le corta la sesion:
``/users/`` ya prohibia la autobaja (``SELF_DEACTIVATION_DENIED``) y por
``/staff/`` el dueno se dejaba afuera de su propio panel.

Lo que NO cambia: un admin de tienda no crea ni asciende admins
(``assert_can_grant_role``) y no toca el acceso de OTRO admin
(``assert_can_change_access``), tampoco su ficha de profesional.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from core.utils import ARGENTINA_TZ
from modules.staff.model import Staff
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    register_and_login,
)

PASSWORD = "Password123!"
DIAS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class Tienda:
    def __init__(self, store: str, token: str, service: str, email: str) -> None:
        self.store = store
        self.token = token
        self.service = service
        self.email = email


async def _tienda(client: AsyncClient, slug: str) -> Tienda:
    email = f"{slug}@t.com"
    store, token = await register_and_login(client, slug=slug, email=email)
    service = await create_service(client, token)
    return Tienda(store, token, service, email)


async def _agregarme(client: AsyncClient, token: str, **cuerpo: Any) -> Any:
    return await client.post("/staff/me", headers=auth_headers(token), json=cuerpo)


async def _cuenta(session: AsyncSession, email: str) -> User:
    return (
        await session.execute(
            select(User)
            .where(User.email == email)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _login(client: AsyncClient, email: str) -> Any:
    return await client.post("/auth/login", json={"email": email, "password": PASSWORD})


async def _otro_admin(
    client: AsyncClient, session: AsyncSession, tienda: Tienda, email: str
) -> str:
    """Segundo admin de la MISMA tienda (lo da de alta el superadmin), logueado."""
    store_id = (
        await session.execute(select(Store.id).where(Store.public_id == tienda.store))
    ).scalar_one()
    session.add(
        User(
            email=email,
            hashed_password=hash_password(PASSWORD),
            first_name="Socia",
            last_name="Dos",
            role=UserRole.ADMIN,
            store_id=store_id,
        )
    )
    await session.commit()
    login = await _login(client, email)
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


async def _usuario_de_rol(
    client: AsyncClient, session: AsyncSession, tienda: Tienda, email: str, role: str
) -> str:
    store_id = (
        await session.execute(select(Store.id).where(Store.public_id == tienda.store))
    ).scalar_one()
    session.add(
        User(
            email=email,
            hashed_password=hash_password(PASSWORD),
            first_name="Otro",
            last_name="Rol",
            role=role,
            store_id=store_id,
        )
    )
    await session.commit()
    login = await _login(client, email)
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


async def _staff_publico(client: AsyncClient, tienda: Tienda) -> dict[str, str]:
    res = await client.get(
        "/public/staff",
        params={"store_public_id": tienda.store, "service_id": tienda.service},
    )
    assert res.status_code == 200, res.text
    return {s["public_id"]: s["display_name"] for s in res.json()}


@pytest.mark.asyncio
async def test_el_duenio_se_agrega_con_su_nombre_y_el_portal_lo_reserva(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda = await _tienda(client, "duenio-reserva")
    cuenta = await _cuenta(test_session, tienda.email)

    res = await _agregarme(client, tienda.token, service_ids=[tienda.service])

    assert res.status_code == 201, res.text
    ficha = res.json()
    # Su misma cuenta: el id del profesional es el de su usuario, con su email
    # y su nombre (seed: "Admin Demo").
    assert ficha["public_id"] == cuenta.id
    assert ficha["email"] == tienda.email
    assert ficha["display_name"] == "Admin Demo"
    assert ficha["service_ids"] == [tienda.service]
    # Ni cuenta nueva ni email repetido, y sigue siendo admin.
    total = (
        await test_session.execute(
            select(func.count()).select_from(User).where(User.email == tienda.email)
        )
    ).scalar_one()
    assert total == 1
    cuenta = await _cuenta(test_session, tienda.email)
    assert cuenta.role == UserRole.ADMIN
    assert (await _login(client, tienda.email)).status_code == 200

    # El portal lo muestra y le ofrece turnos (sin franjas: horario del local).
    assert (await _staff_publico(client, tienda))[cuenta.id] == "Admin Demo"
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    local = dia.astimezone(ARGENTINA_TZ).date()
    horario = await client.patch(
        "/stores/me",
        headers=auth_headers(tienda.token),
        json={
            "business_hours": {
                DIAS[local.weekday()]: [{"open": "09:00", "close": "18:00"}]
            }
        },
    )
    assert horario.status_code == 200, horario.text
    slots = await client.get(
        "/public/availability",
        params={
            "store_public_id": tienda.store,
            "service_id": tienda.service,
            "date": local.isoformat(),
        },
    )
    assert slots.status_code == 200, slots.text
    suyos = [
        s
        for s in slots.json()
        if s["staff_id"] == cuenta.id and s["status"] == "available"
    ]
    assert suyos, "el dueno agregado como profesional tiene que tener turnos"

    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": tienda.store,
            "service_id": tienda.service,
            "staff_id": cuenta.id,
            "starts_at": suyos[0]["starts_at"],
            "client_name": "Cliente del dueno",
            "client_phone": "+5491155550123",
            "accepts_terms": True,
            "idempotency_key": "duenio-reserva-1",
        },
    )
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["staff_id"] == cuenta.id


@pytest.mark.asyncio
async def test_sin_nombre_visible_usa_el_de_la_cuenta_y_acepta_uno_propio(
    client: AsyncClient,
) -> None:
    tienda = await _tienda(client, "duenio-nombre")

    res = await _agregarme(client, tienda.token, display_name="Enrique (dueño)")

    assert res.status_code == 201, res.text
    assert res.json()["display_name"] == "Enrique (dueño)"
    assert res.json()["service_ids"] == []


@pytest.mark.asyncio
async def test_agregarse_dos_veces_es_409(client: AsyncClient) -> None:
    tienda = await _tienda(client, "duenio-dos-veces")
    assert (await _agregarme(client, tienda.token)).status_code == 201

    res = await _agregarme(client, tienda.token)

    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "STAFF_SELF_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_quitarse_de_la_agenda_no_le_toca_el_acceso(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda = await _tienda(client, "duenio-quitarse")
    ficha = (
        await _agregarme(client, tienda.token, service_ids=[tienda.service])
    ).json()

    baja = await client.delete(
        f"/staff/{ficha['public_id']}", headers=auth_headers(tienda.token)
    )

    assert baja.status_code == 204, baja.text
    cuenta = await _cuenta(test_session, tienda.email)
    assert cuenta.is_active is True
    # La sesion sigue viva (no se revocaron sus sesiones) y puede volver a entrar.
    lista = await client.get("/staff/", headers=auth_headers(tienda.token))
    assert lista.status_code == 200, lista.text
    assert ficha["public_id"] not in {s["public_id"] for s in lista.json()}
    assert (await _login(client, tienda.email)).status_code == 200
    assert ficha["public_id"] not in await _staff_publico(client, tienda)

    # Volver a agregarse reactiva la MISMA ficha.
    otra_vez = await _agregarme(client, tienda.token, service_ids=[tienda.service])
    assert otra_vez.status_code == 201, otra_vez.text
    assert otra_vez.json()["public_id"] == ficha["public_id"]
    assert ficha["public_id"] in await _staff_publico(client, tienda)


@pytest.mark.asyncio
async def test_pausarse_por_put_tampoco_le_toca_el_acceso(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda = await _tienda(client, "duenio-pausa")
    ficha = (await _agregarme(client, tienda.token)).json()

    res = await client.put(
        f"/staff/{ficha['public_id']}",
        headers=auth_headers(tienda.token),
        json={"is_active": False},
    )

    assert res.status_code == 200, res.text
    assert res.json()["is_active"] is False
    assert (await _cuenta(test_session, tienda.email)).is_active is True
    assert (
        await client.get("/staff/", headers=auth_headers(tienda.token))
    ).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["staff", "receptionist"])
async def test_profesional_y_recepcion_no_usan_agregarme(
    client: AsyncClient, test_session: AsyncSession, rol: str
) -> None:
    tienda = await _tienda(client, f"duenio-rol-{rol}")
    token = await _usuario_de_rol(
        client, test_session, tienda, f"{rol}-duenio@t.com", rol
    )

    res = await _agregarme(client, token)

    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_un_admin_no_vuelve_reservable_a_otro_admin(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Agregarme es SOLO para uno mismo; la ficha de otro admin sigue cerrada."""
    tienda = await _tienda(client, "duenio-otro-admin")
    token_b = await _otro_admin(client, test_session, tienda, "socia-duenio@t.com")

    # Por POST /staff/ con el email de la otra admin: no hay segunda cuenta.
    alta = await client.post(
        "/staff/",
        headers=auth_headers(tienda.token),
        json={
            "display_name": "Socia",
            "first_name": "Socia",
            "last_name": "Dos",
            "email": "socia-duenio@t.com",
            "service_ids": [tienda.service],
        },
    )
    assert alta.status_code in (409, 422), alta.text
    assert await _staff_publico(client, tienda) == {}

    # Ella se agrega sola; el otro admin no le puede quitar la agenda ni pausarla
    # (es su acceso: assert_can_change_access), y tampoco cambiarle el email.
    suya = (await _agregarme(client, token_b, service_ids=[tienda.service])).json()
    baja = await client.delete(
        f"/staff/{suya['public_id']}", headers=auth_headers(tienda.token)
    )
    assert baja.status_code == 403, baja.text
    for cuerpo in ({"is_active": False}, {"email": "toma@t.com"}):
        res = await client.put(
            f"/staff/{suya['public_id']}",
            headers=auth_headers(tienda.token),
            json=cuerpo,
        )
        assert res.status_code == 403, (cuerpo, res.text)
    cuenta_b = await _cuenta(test_session, "socia-duenio@t.com")
    assert cuenta_b.is_active is True
    assert cuenta_b.role == UserRole.ADMIN
    assert suya["public_id"] in await _staff_publico(client, tienda)


# 2026-10-08 (revision de #133). Sintoma: con su ficha de profesional, el
# admin cambiaba el email de LOGIN de su propia cuenta por
# ``PUT /staff/{su id}`` sin la contrasena (``update_profile`` sincroniza
# ``user.email`` y ``assert_can_change_access`` deja pasar a uno mismo).
# Una sesion robada se quedaba con la cuenta: el "olvide mi contrasena" le
# llegaba al atacante. ``/users/`` ya niega lo mismo con la contrasena
# (``SELF_PASSWORD_CHANGE_DENIED``).


@pytest.mark.asyncio
async def test_el_admin_no_cambia_su_email_de_login_por_staff(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda = await _tienda(client, "duenio-email-propio")
    ficha = (await _agregarme(client, tienda.token)).json()

    res = await client.put(
        f"/staff/{ficha['public_id']}",
        headers=auth_headers(tienda.token),
        json={"email": "atacante-duenio@x.com"},
    )

    assert res.status_code == 400, res.text
    assert res.json()["error_code"] == "SELF_EMAIL_CHANGE_DENIED"
    cuenta = await _cuenta(test_session, tienda.email)
    assert cuenta.email == tienda.email
    assert (await _login(client, tienda.email)).status_code == 200
    assert (await _login(client, "atacante-duenio@x.com")).status_code == 401
    detalle = await client.get(
        f"/staff/{ficha['public_id']}", headers=auth_headers(tienda.token)
    )
    assert detalle.json()["email"] == tienda.email


@pytest.mark.asyncio
async def test_el_admin_puede_reenviar_su_mismo_email_al_editarse(
    client: AsyncClient,
) -> None:
    """El formulario manda el email tal cual: el mismo (otra caja o espacios) pasa."""
    tienda = await _tienda(client, "duenio-email-igual")
    ficha = (await _agregarme(client, tienda.token)).json()

    for email in (tienda.email, f"  {tienda.email.upper()} "):
        res = await client.put(
            f"/staff/{ficha['public_id']}",
            headers=auth_headers(tienda.token),
            json={"email": email, "display_name": "Dueno que atiende"},
        )
        assert res.status_code == 200, (email, res.text)
        assert res.json()["email"] == tienda.email
    assert (await _login(client, tienda.email)).status_code == 200


@pytest.mark.asyncio
async def test_el_admin_sigue_cambiando_el_email_de_un_profesional(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda = await _tienda(client, "duenio-email-pro")
    alta = await client.post(
        "/staff/",
        headers=auth_headers(tienda.token),
        json={
            "display_name": "Pro",
            "first_name": "Pro",
            "last_name": "Fesional",
            "email": "pro-viejo-duenio@t.com",
            "service_ids": [tienda.service],
        },
    )
    assert alta.status_code == 201, alta.text

    res = await client.put(
        f"/staff/{alta.json()['public_id']}",
        headers=auth_headers(tienda.token),
        json={"email": "pro-nuevo-duenio@t.com"},
    )

    assert res.status_code == 200, res.text
    assert res.json()["email"] == "pro-nuevo-duenio@t.com"
    cuenta = (
        await test_session.execute(
            select(User)
            .where(User.id == alta.json()["public_id"])
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert cuenta.email == "pro-nuevo-duenio@t.com"


# 2026-10-08 (revision de #133). Sintoma: el superadmin se agregaba como
# profesional; las lecturas del panel de la tienda lo esconden (S-15,
# AUD2-B3-11) pero el portal publico lo ofrecia para reservar. La cuenta
# global no atiende en ninguna tienda.


@pytest.mark.asyncio
async def test_el_superadmin_no_se_agrega_como_profesional(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    tienda = await _tienda(client, "duenio-global")
    cuenta = await _cuenta(test_session, tienda.email)
    cuenta.is_global_admin = True
    await test_session.commit()

    res = await _agregarme(client, tienda.token, service_ids=[tienda.service])

    assert res.status_code == 403, res.text
    assert res.json()["error_code"] == "STAFF_SELF_GLOBAL_ADMIN_DENIED"
    fichas = (
        await test_session.execute(
            select(func.count()).select_from(Staff).where(Staff.id == cuenta.id)
        )
    ).scalar_one()
    assert fichas == 0
    assert await _staff_publico(client, tienda) == {}
