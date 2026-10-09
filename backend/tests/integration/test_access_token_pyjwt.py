"""El access token de punta a punta con PyJWT (D-20260930-04, 2026-10-02).

``auth.dependencies._authenticate`` cambio ``jose.JWTError`` por
``jwt.InvalidTokenError``. Si algun token malo levantara una excepcion fuera de
esa jerarquia, el request responderia 500 en vez de 401; y el ``sid`` es lo
que ata el access token a una sesion revocable (regla 15). Se prueba por HTTP,
con la clave real de la app.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest
from httpx import AsyncClient
from structlog.testing import capture_logs

from core.config import settings
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    register_and_login,
)


def _reemitir(token: str, **cambios: Any) -> str:
    """Los claims del token real, cambiados y firmados con la clave real.

    Un ``timedelta`` es un corrimiento desde ahora, resuelto al firmar (no al
    coleccionar el ``parametrize``, que puede ser mucho antes de correr).
    """
    claims = jwt.decode(token, options={"verify_signature": False})
    ahora = datetime.now(timezone.utc)
    claims.update(
        {
            k: int((ahora + v).timestamp()) if isinstance(v, timedelta) else v
            for k, v in cambios.items()
        }
    )
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


@pytest.mark.asyncio
async def test_el_token_del_login_lleva_sid_y_autentica(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="pyjwt-ok", email="pyjwt-ok@test.com"
    )

    claims = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=["HS256"],
        audience=settings.JWT_AUDIENCE,
        issuer=settings.JWT_ISSUER,
    )
    assert isinstance(claims["sid"], str) and claims["sid"]
    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    res = await client.get("/me", headers=auth_headers(token))
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cambios",
    [
        {"sid": None},
        {"sid": 123},
        {"sid": "01J9ZSESIONQUENOEXISTE0000"},
        {"exp": -timedelta(seconds=5)},
        {"aud": "otro-sistema"},
        {"iss": "otro-emisor"},
        {"sub": None},
        {"sub": 42},
        {"iat": timedelta(hours=1)},
    ],
    ids=[
        "sin-sid",
        "sid-no-string",
        "sid-inexistente",
        "vencido",
        "aud-ajena",
        "iss-ajeno",
        "sin-sub",
        "sub-no-string",
        "iat-futuro",
    ],
)
async def test_token_con_la_clave_real_pero_invalido_es_401(
    client: AsyncClient, cambios: dict[str, Any]
) -> None:
    _, token = await register_and_login(
        client, slug="pyjwt-malo", email="pyjwt-malo@test.com"
    )

    res = await client.get("/me", headers=auth_headers(_reemitir(token, **cambios)))

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        "no-es-un-jwt",
        "a.b.c",
        # alg none, sin firma.
        "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJ4In0.",
    ],
    ids=["basura", "tres-partes-basura", "alg-none"],
)
async def test_token_ilegible_es_401_no_500(client: AsyncClient, token: str) -> None:
    res = await client.get("/me", headers=auth_headers(token))

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_el_rechazo_se_loguea_por_clase_sin_el_token(
    client: AsyncClient,
) -> None:
    """Observabilidad del rechazo: la clase de la excepcion de PyJWT va al log
    (para distinguir vencidos de forjados), el token y sus claims no."""
    _, token = await register_and_login(
        client, slug="pyjwt-log", email="pyjwt-log@test.com"
    )
    vencido = _reemitir(token, exp=-timedelta(seconds=5))
    claims = jwt.decode(vencido, options={"verify_signature": False})

    with capture_logs() as logs:
        res = await client.get("/me", headers=auth_headers(vencido))

    assert res.status_code == 401, res.text
    rechazos = [e for e in logs if e["event"] == "access_token_rejected"]
    assert rechazos == [
        {
            "event": "access_token_rejected",
            "reason": "ExpiredSignatureError",
            "log_level": "info",
        }
    ]
    volcado = repr(logs)
    for secreto in (vencido, claims["sub"], claims["sid"], claims["jti"]):
        assert secreto not in volcado


@pytest.mark.asyncio
async def test_otro_algoritmo_con_la_clave_real_es_401(client: AsyncClient) -> None:
    _, token = await register_and_login(
        client, slug="pyjwt-alg", email="pyjwt-alg@test.com"
    )
    claims = jwt.decode(token, options={"verify_signature": False})
    hs512 = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS512")

    res = await client.get("/me", headers=auth_headers(hs512))

    assert res.status_code == 401, res.text
