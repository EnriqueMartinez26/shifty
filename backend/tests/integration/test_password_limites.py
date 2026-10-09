"""Limites de la contrasena al FIJARLA (D-20261001-01, 2026-10-01).

Decision del dueno: al fijar una contrasena el piso es 6 caracteres, el techo
64 y, ademas, 72 bytes en UTF-8 (bcrypt solo mira los primeros 72: antes
``core/security.py`` los recortaba en silencio y una clave de 64 letras con
acento llegaba a 128 bytes). Pasar los 72 bytes se RECHAZA con 422 y un mensaje
claro, nunca se trunca. La regla de letra + numero y la denylist no cambian.

El LOGIN no cambia: acepta de 1 a 128 caracteres y verifica igual que siempre,
asi un hash hecho con una clave larga antes de este cambio sigue sirviendo.

Los seis caminos donde se FIJA una clave: reset, cambio propio, alta y edicion
en el panel (``/users``) y alta y edicion por el superadmin. El bootstrap del
superadmin lo cubre ``tests/unit/test_password_politica.py``.

Los casos usan numeros literales (no las constantes de ``core.validation``) a
proposito: si alguien mueve un tope sin pasar por la decision, este test cae.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password_reset_token
from modules.users.model import User
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
    seed_store_and_admin,
)

PASSWORD_ACTUAL = "Password123!"
TOKEN_DE_RESET = "token-de-prueba-para-reset-1234567890"

# (cuenta que inicia sesion con la clave nueva si se acepta, respuesta)
Resultado = tuple[str, Response]
Flujo = Callable[[AsyncClient, AsyncSession, str], Awaitable[Resultado]]


async def _reset(
    client: AsyncClient, session: AsyncSession, password: str
) -> Resultado:
    email = "reset@test.com"
    await seed_store_and_admin(slug="pw-reset", email=email)
    usuario = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one()
    usuario.password_reset_token_hash = hash_password_reset_token(TOKEN_DE_RESET)
    usuario.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=30
    )
    await session.commit()
    respuesta = await client.post(
        "/auth/reset-password",
        json={"token": TOKEN_DE_RESET, "new_password": password},
    )
    return email, respuesta


async def _cambio_propio(
    client: AsyncClient, session: AsyncSession, password: str
) -> Resultado:
    email = "cambio@test.com"
    _tienda, token = await register_and_login(client, slug="pw-cambio", email=email)
    respuesta = await client.put(
        "/auth/change-password",
        headers=auth_headers(token),
        json={"current_password": PASSWORD_ACTUAL, "new_password": password},
    )
    return email, respuesta


def _alta_del_panel(email: str, password: str) -> dict[str, Any]:
    return {
        "email": email,
        "first_name": "Ana",
        "last_name": "Perez",
        "password": password,
        "role": "staff",
    }


async def _panel_alta(
    client: AsyncClient, session: AsyncSession, password: str
) -> Resultado:
    _tienda, token = await register_and_login(
        client, slug="pw-panel-alta", email="admin-alta@test.com"
    )
    email = "nuevo@test.com"
    respuesta = await client.post(
        "/users/",
        headers=auth_headers(token),
        json=_alta_del_panel(email, password),
    )
    return email, respuesta


async def _panel_edicion(
    client: AsyncClient, session: AsyncSession, password: str
) -> Resultado:
    _tienda, token = await register_and_login(
        client, slug="pw-panel-edit", email="admin-edit@test.com"
    )
    email = "editado@test.com"
    alta = await client.post(
        "/users/",
        headers=auth_headers(token),
        json=_alta_del_panel(email, PASSWORD_ACTUAL),
    )
    assert alta.status_code == 201, alta.text
    respuesta = await client.patch(
        f"/users/{alta.json()['public_id']}",
        headers=auth_headers(token),
        json={"password": password},
    )
    return email, respuesta


async def _superadmin_headers(
    client: AsyncClient, session: AsyncSession, slug: str
) -> tuple[str, dict[str, str]]:
    """Siembra una tienda, promueve a su admin a global y devuelve su id y headers."""
    email = f"super-{slug}@test.com"
    tienda = await seed_store_and_admin(slug=slug, email=email)
    admin = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one()
    admin.is_global_admin = True
    await session.commit()
    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD_ACTUAL}
    )
    assert login.status_code == 200, login.text
    return tienda, auth_headers(login.json()["access_token"])


def _alta_de_admin(email: str, password: str) -> dict[str, Any]:
    return {
        "email": email,
        "password": password,
        "first_name": "Ana",
        "last_name": "Perez",
    }


async def _superadmin_alta(
    client: AsyncClient, session: AsyncSession, password: str
) -> Resultado:
    tienda, headers = await _superadmin_headers(client, session, "pw-super-alta")
    email = "admin-nuevo@test.com"
    respuesta = await client.post(
        f"/superadmin/stores/{tienda}/admins",
        headers=headers,
        json=_alta_de_admin(email, password),
    )
    return email, respuesta


async def _superadmin_edicion(
    client: AsyncClient, session: AsyncSession, password: str
) -> Resultado:
    tienda, headers = await _superadmin_headers(client, session, "pw-super-edit")
    email = "admin-editado@test.com"
    alta = await client.post(
        f"/superadmin/stores/{tienda}/admins",
        headers=headers,
        json=_alta_de_admin(email, PASSWORD_ACTUAL),
    )
    assert alta.status_code == 201, alta.text
    respuesta = await client.patch(
        f"/superadmin/users/{alta.json()['public_id']}",
        headers=headers,
        json={"password": password},
    )
    return email, respuesta


FLUJOS = [
    pytest.param(_reset, id="reset-password"),
    pytest.param(_cambio_propio, id="cambio-propio"),
    pytest.param(_panel_alta, id="panel-alta"),
    pytest.param(_panel_edicion, id="panel-edicion"),
    pytest.param(_superadmin_alta, id="superadmin-alta"),
    pytest.param(_superadmin_edicion, id="superadmin-edicion"),
]

# 35 letras de 2 bytes + "12": 37 caracteres y exactamente 72 bytes.
SETENTA_Y_DOS_BYTES = "á" * 35 + "12"

ACEPTADAS = [
    pytest.param("abcde1", id="piso-de-6"),
    pytest.param("a" * 63 + "1", id="tope-de-64-caracteres"),
    pytest.param(SETENTA_Y_DOS_BYTES, id="72-bytes-exactos"),
]

# (clave, fragmento que tiene que aparecer en el mensaje del 422)
RECHAZADAS = [
    pytest.param("abc12", "6 characters", id="5-caracteres"),
    pytest.param("a" * 64 + "1", "64 characters", id="65-caracteres"),
    pytest.param("á" * 36 + "1", "72 bytes", id="73-bytes"),
    pytest.param("á" * 36 + "12", "72 bytes", id="74-bytes"),
    pytest.param("á" * 63 + "1", "72 bytes", id="64-caracteres-de-2-bytes"),
    pytest.param("abcdefgh", "numero", id="sin-numero"),
    pytest.param("12345678", "letra", id="sin-letra"),
    pytest.param("password1234", "comun", id="denylist"),
    pytest.param("PassWord1234", "comun", id="denylist-sin-importar-mayusculas"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("flujo", FLUJOS)
@pytest.mark.parametrize("password", ACEPTADAS)
async def test_la_clave_dentro_de_los_limites_se_acepta_y_sirve_para_entrar(
    client: AsyncClient, test_session: AsyncSession, flujo: Flujo, password: str
) -> None:
    email, respuesta = await flujo(client, test_session, password)
    assert respuesta.status_code in {200, 201, 204}, respuesta.text

    entra = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert entra.status_code == 200, entra.text


@pytest.mark.asyncio
@pytest.mark.parametrize("flujo", FLUJOS)
@pytest.mark.parametrize(("password", "fragmento"), RECHAZADAS)
async def test_la_clave_fuera_de_los_limites_se_rechaza_con_422(
    client: AsyncClient,
    test_session: AsyncSession,
    flujo: Flujo,
    password: str,
    fragmento: str,
) -> None:
    _email, respuesta = await flujo(client, test_session, password)

    assert respuesta.status_code == 422, respuesta.text
    assert fragmento in respuesta.json()["message"], respuesta.text


# --- El login NO cambia: 1 a 128 caracteres, verificacion de siempre ---------


@pytest.mark.asyncio
@pytest.mark.parametrize("largo", [100, 128])
async def test_el_login_sigue_aceptando_la_clave_larga_de_antes(
    client: AsyncClient, largo: int
) -> None:
    # Cuentas con un hash hecho ANTES del cambio: 100 y 128 caracteres, ambas
    # por encima del nuevo techo de 64. bcrypt las recorta a 72 bytes al
    # hashear y al verificar; no se toca.
    clave = "a" * (largo - 1) + "1"
    await seed_store_and_admin(
        slug=f"pw-login-{largo}", email=f"largo{largo}@test.com", password=clave
    )

    entra = await client.post(
        "/auth/login", json={"email": f"largo{largo}@test.com", "password": clave}
    )
    assert entra.status_code == 200, entra.text


@pytest.mark.asyncio
async def test_el_login_rechaza_129_caracteres_con_422(client: AsyncClient) -> None:
    respuesta = await client.post(
        "/auth/login", json={"email": "alguien@test.com", "password": "a" * 129}
    )
    assert respuesta.status_code == 422, respuesta.text


@pytest.mark.asyncio
async def test_el_login_sigue_sin_piso_una_clave_corta_da_401_no_422(
    client: AsyncClient,
) -> None:
    # Una clave que la politica de alta rechazaria (5 caracteres) no se revela
    # en el login: es un 401 generico, como hasta hoy.
    await seed_store_and_admin(slug="pw-login-corta", email="corta@test.com")
    respuesta = await client.post(
        "/auth/login", json={"email": "corta@test.com", "password": "abc12"}
    )
    assert respuesta.status_code == 401, respuesta.text


@pytest.mark.asyncio
async def test_la_clave_actual_del_cambio_propio_sigue_sin_piso_ni_techo_de_64(
    client: AsyncClient,
) -> None:
    # `current_password` es la de una cuenta ya existente: 1 a 128, sin la
    # politica de alta. Una de 100 caracteres no es un 422.
    _tienda, token = await register_and_login(
        client, slug="pw-actual", email="actual@test.com"
    )
    respuesta = await client.put(
        "/auth/change-password",
        headers=auth_headers(token),
        json={"current_password": "a" * 100, "new_password": "NuevaPassword456!"},
    )
    # 401 por no ser la clave real, pero pasa la validacion del body.
    assert respuesta.status_code != 422, respuesta.text
