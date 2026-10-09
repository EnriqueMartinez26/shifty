"""Reuso de un refresh ya rotado: una sola implementacion y un test que la ejerce.

Auditoria B3-09, 2026-09-17. Sintoma: ``refresh_session`` tenia 83 lineas y
repetia LITERALMENTE el manejo de reuso en dos ramas (el token llega ya
revocado, y el UPDATE condicional de la rotacion que pierde la carrera):
``revoke_sessions_for_user`` + ``commit`` + ``logger.warning`` +
``AuthenticationException``. Una metrica o un cambio de politica agregado en
una copia no llegaba a la otra. Ademas ``rg -n "reuse" backend/tests/`` daba
cero: la deteccion de robo de refresh no tenia ninguna prueba.

Regla 15 de CLAUDE.md: la revocacion de la familia entera se conserva; lo que
cambia es que vive en un solo lugar.

2026-09-28, D-20260928-01. Sintoma: dos pestanas que refrescaban a la vez, o un
reintento tras una respuesta de refresh perdida, deslogueaban al usuario en
todos sus dispositivos: el segundo en llegar caia en el reuso y revocaba todo.
Reusar un refresh revocado POR ROTACION hace menos de
``REFRESH_REUSE_GRACE_SECONDS`` da 401 sin tocar las demas sesiones; fuera de
la ventana, o si lo revoco un logout, se revoca la familia como siempre. La
carrera concurrente de verdad se prueba en
``tests/postgres/test_pg_rafaga_refresh.py``.
"""

import ast
import inspect
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.auth.router import REFRESH_COOKIE
from modules.auth.service import (
    REFRESH_REUSE_GRACE_SECONDS,
    hash_token,
    refresh_session,
)
from modules.auth.session_model import AuthSession
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)

MAX_LINEAS = 80


def test_refresh_session_entra_en_el_tope_de_lineas_de_la_regla_29() -> None:
    source = inspect.getsource(refresh_session)
    cuerpo = ast.parse(source.lstrip()).body[0]
    assert isinstance(cuerpo, ast.AsyncFunctionDef)
    lineas = (cuerpo.end_lineno or 0) - cuerpo.lineno + 1
    assert lineas <= MAX_LINEAS, (
        f"refresh_session tiene {lineas} lineas (tope {MAX_LINEAS}, regla 29)."
    )


def test_el_manejo_de_reuso_esta_escrito_una_sola_vez() -> None:
    source = inspect.getsource(refresh_session)
    assert source.count("refresh_token_reuse_detected") == 0, (
        "refresh_session vuelve a loguear el reuso inline: el manejo va en "
        "_handle_refresh_reuse, que lo centraliza para las dos ramas."
    )
    assert source.count("_handle_refresh_reuse(") == 2, (
        "las dos ramas de reuso (token ya revocado y rotacion que pierde la "
        "carrera) deben llamar al mismo helper."
    )


async def _otro_dispositivo(client: AsyncClient, email: str) -> str:
    """Segundo login del mismo usuario: una sesion independiente de la familia."""
    login = await client.post(
        "/auth/login", json={"email": email, "password": "Password123!"}
    )
    assert login.status_code == 200, login.text
    otro = client.cookies.get(REFRESH_COOKIE)
    assert otro
    return otro


def _usar(client: AsyncClient, refresh: str) -> None:
    """Deja en el jar SOLO este refresh.

    El jar guarda las cookies que setea el server con su dominio; un ``set`` a
    mano agrega otra con el mismo nombre y ``client.cookies.get`` falla por
    conflicto. Por eso el refresh nuevo se lee de la respuesta.
    """
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, refresh)


async def _envejecer_revocacion(test_session: AsyncSession, refresh: str) -> None:
    """Simula que la revocacion ocurrio antes de la ventana de gracia."""
    hace_rato = datetime.now(timezone.utc) - timedelta(
        seconds=REFRESH_REUSE_GRACE_SECONDS + 5
    )
    await test_session.execute(
        update(AuthSession)
        .where(AuthSession.refresh_token_hash == hash_token(refresh))
        .values(revoked_at=hace_rato)
    )
    await test_session.commit()


async def _vivas(test_session: AsyncSession) -> int:
    return int(
        (
            await test_session.execute(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.revoked_at.is_(None))
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_reusar_un_refresh_ya_rotado_mata_la_familia_entera(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _, token = await register_and_login(
        client, slug="reuso-refresh", email="reuso@test.com"
    )
    viejo = client.cookies.get(REFRESH_COOKIE)
    assert viejo, "el login no dejo la cookie de refresh"

    # Rotacion normal: el refresh viejo queda revocado y nace uno nuevo.
    rotacion = await client.post("/auth/refresh")
    assert rotacion.status_code == 200, rotacion.text
    nuevo = client.cookies.get(REFRESH_COOKIE)
    assert nuevo and nuevo != viejo, "el refresh no roto"

    # El atacante (o la victima) presenta el token viejo pasada la ventana de
    # gracia (D-20260928-01): senal de robo.
    await _envejecer_revocacion(test_session, viejo)
    client.cookies.set(REFRESH_COOKIE, viejo)
    reuso = await client.post("/auth/refresh")
    assert reuso.status_code in {401, 403}, reuso.text

    # La familia entera cae: el refresh NUEVO tampoco sirve ya.
    client.cookies.set(REFRESH_COOKIE, nuevo)
    despues = await client.post("/auth/refresh")
    assert despues.status_code in {401, 403}, (
        "el refresh legitimo sobrevivio al reuso: la familia no se revoco"
    )

    # Y el access token emitido antes tampoco, porque cuelga del sid revocado.
    muerto = await client.get("/me", headers=auth_headers(token))
    assert muerto.status_code in {401, 403}


@pytest.mark.asyncio
async def test_el_reuso_dentro_de_la_ventana_no_cierra_las_demas_sesiones(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    email = "reuso-gracia@test.com"
    await register_and_login(client, slug="reuso-gracia", email=email)
    viejo = client.cookies.get(REFRESH_COOKIE)
    assert viejo
    otro = await _otro_dispositivo(client, email)

    _usar(client, viejo)
    rotacion = await client.post("/auth/refresh")
    assert rotacion.status_code == 200, rotacion.text
    nuevo = rotacion.cookies.get(REFRESH_COOKIE)
    assert nuevo and nuevo != viejo

    # La segunda pestana (o el reintento) llega con el refresh recien rotado.
    _usar(client, viejo)
    reuso = await client.post("/auth/refresh")
    assert reuso.status_code == 401, reuso.text
    assert REFRESH_COOKIE not in reuso.cookies, "el reuso emitio tokens nuevos"
    assert reuso.json().get("access_token") is None

    # Ni la sesion rotada ni la del otro dispositivo cayeron.
    assert await _vivas(test_session) == 2
    for refresh in (nuevo, otro):
        _usar(client, refresh)
        sigue = await client.post("/auth/refresh")
        assert sigue.status_code == 200, sigue.text


@pytest.mark.asyncio
async def test_reusar_un_refresh_cerrado_por_logout_revoca_todo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    email = "reuso-logout@test.com"
    await register_and_login(client, slug="reuso-logout", email=email)
    cerrado = client.cookies.get(REFRESH_COOKIE)
    assert cerrado
    otro = await _otro_dispositivo(client, email)

    _usar(client, cerrado)
    salida = await client.post("/auth/logout")
    assert salida.status_code == 204, salida.text

    # El logout no es una rotacion: no hay ventana de gracia aunque sea ya.
    _usar(client, cerrado)
    reuso = await client.post("/auth/refresh")
    assert reuso.status_code == 401, reuso.text
    assert await _vivas(test_session) == 0
    _usar(client, otro)
    assert (await client.post("/auth/refresh")).status_code == 401
