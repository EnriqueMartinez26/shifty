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
"""

import ast
import inspect
import pytest
from httpx import AsyncClient

from modules.auth.router import REFRESH_COOKIE
from modules.auth.service import refresh_session
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


@pytest.mark.asyncio
async def test_reusar_un_refresh_ya_rotado_mata_la_familia_entera(
    client: AsyncClient,
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

    # El atacante (o la victima) presenta el token viejo: senal de robo.
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
