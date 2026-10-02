"""Access token con PyJWT en lugar de python-jose (D-20260930-04, 2026-10-02).

python-jose arrastraba ``ecdsa`` (PYSEC-2026-1325, timing Minerva en P-256, sin
fix) aunque Shifty firma solo con HS256. Al cambiar de libreria lo que no se
puede romper: un token HS256 ya emitido por python-jose sigue valiendo (no se
cierran las sesiones abiertas el dia del deploy) y todo token malo cae en
``jwt.InvalidTokenError``, la excepcion que ``auth.dependencies`` traduce a
401. Si alguno de estos casos levantara otra cosa, el request responderia 500
en vez de 401.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest
from pydantic import ValidationError

from core import security
from core.config import Settings, settings

# Clave propia de los tokens de compatibilidad (64 bytes, como el SECRET_KEY
# de tests, pero fija: si la de conftest cambia, los tokens de abajo siguen
# verificando).
CLAVE_LARGA = "test-only-dedicated-jwt-key-not-a-secret-0123456789abcdefghijklm"

# Timestamps fijos para firmar tokens a mano (alg none, confusion de
# algoritmo): exp = 2100-01-01T00:00:00Z, iat = 2026-09-21T14:13:20Z. Lejos
# de vencer y en el pasado, para que el unico motivo de rechazo sea el ``alg``.
EXP_2100 = 4102444800
IAT_PASADO = 1790000000

# Tokens emitidos el 2026-10-02 con python-jose 3.5.0 de verdad, en un entorno
# descartable fuera del venv del proyecto:
#   uv run --no-project --with "python-jose[cryptography]==3.5.0" \
#       --with "pyjwt==2.15.1" python mint.py
# ``mint.py`` copia el cuerpo de ``create_access_token`` de origin/main (antes
# del cambio: ``jose.jwt.encode`` con exp/iat datetime, jti uuid4, iss y aud)
# con CLAVE_LARGA, ``expires_delta`` de 70 anios (vence en 2096) y los claims
# exactos de ``auth.service.access_token_for_user``: sub, sid, store_id, role
# e is_global_admin. HS256 da los MISMOS bytes con las dos librerias para los
# mismos claims (cabecera y cuerpo JSON compactos, en el mismo orden; el
# script lo comprobo re-firmando con PyJWT), asi que estos tokens prueban
# compatibilidad de cable, no solo de API.
TOKEN_JOSE_SUPERADMIN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIwMUo5WlNVUEVSQURNSU4wMDAwMDAwMDAwIiwic2lkIjoiMDFKOVpTRVNJT05TVVBFUk"
    "FETUlOMDAwMCIsInN0b3JlX2lkIjpudWxsLCJyb2xlIjoic3VwZXJfYWRtaW4iLCJpc19nbG9iYWxf"
    "YWRtaW4iOnRydWUsImV4cCI6Mzk5ODQ1ODAyMSwiaWF0IjoxNzkwOTM4MDIxLCJqdGkiOiJmNTAwYj"
    "JjMS1iYjI2LTQ3NTAtYjJmMS01NjMyM2MyNjQ3OGMiLCJpc3MiOiJzaGlmdHktYXBpIiwiYXVkIjoi"
    "c2hpZnR5In0."
    "uD1OsoazZuaYY9vIlsfB2EGGsPv_elpS14t16pBoliY"
)
TOKEN_JOSE_ADMIN_DE_TIENDA = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIwMUo5WkFETUlOREVUSUVOREEwMDAwMDAwIiwic2lkIjoiMDFKOVpTRVNJT05BRE1JTj"
    "AwMDAwMDAwMCIsInN0b3JlX2lkIjoiMDFKOVpUSUVOREEwMDAwMDAwMDAwMDAwMCIsInJvbGUiOiJz"
    "dG9yZV9hZG1pbiIsImlzX2dsb2JhbF9hZG1pbiI6ZmFsc2UsImV4cCI6Mzk5ODQ1ODAyMSwiaWF0Ij"
    "oxNzkwOTM4MDIxLCJqdGkiOiIwYTJlM2QyMy0xMTU0LTQzMWQtOGJjNi0yNTExZWFhOGNkM2UiLCJp"
    "c3MiOiJzaGlmdHktYXBpIiwiYXVkIjoic2hpZnR5In0."
    "Ecq1AByjcRJUxQlWqjJdjlGHuUBK3VoiWqJbbDch34s"
)


def _b64(parte: dict[str, Any]) -> str:
    crudo = json.dumps(parte, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(crudo).rstrip(b"=").decode()


def _claims(**cambios: Any) -> dict[str, Any]:
    ahora = datetime.now(timezone.utc)
    claims: dict[str, Any] = {
        "sub": "01J9ZUSUARIO0000000000000",
        "sid": "01J9ZSESION00000000000000",
        "exp": ahora + timedelta(minutes=5),
        "iat": ahora,
        "jti": "6f1e0a4c-2b7d-4c3e-8a9f-1d2e3f4a5b6c",
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    claims.update(cambios)
    return {k: v for k, v in claims.items() if v is not None}


def _firmar(
    claims: dict[str, Any], clave: str | None = None, alg: str = "HS256"
) -> str:
    return jwt.encode(claims, clave or settings.SECRET_KEY, algorithm=alg)


# --- compatibilidad con lo que emitio python-jose ---------------------------


@pytest.mark.parametrize(
    ("token", "esperado"),
    [
        (
            TOKEN_JOSE_SUPERADMIN,
            {
                "sub": "01J9ZSUPERADMIN0000000000",
                "sid": "01J9ZSESIONSUPERADMIN0000",
                "store_id": None,
                "role": "super_admin",
                "is_global_admin": True,
                "exp": 3998458021,
                "iat": 1790938021,
                "jti": "f500b2c1-bb26-4750-b2f1-56323c26478c",
                "iss": "shifty-api",
                "aud": "shifty",
            },
        ),
        (
            TOKEN_JOSE_ADMIN_DE_TIENDA,
            {
                "sub": "01J9ZADMINDETIENDA0000000",
                "sid": "01J9ZSESIONADMIN000000000",
                "store_id": "01J9ZTIENDA00000000000000",
                "role": "store_admin",
                "is_global_admin": False,
                "exp": 3998458021,
                "iat": 1790938021,
                "jti": "0a2e3d23-1154-431d-8bc6-2511eaa8cd3e",
                "iss": "shifty-api",
                "aud": "shifty",
            },
        ),
    ],
    ids=["superadmin-store-id-null", "admin-de-tienda"],
)
def test_un_token_emitido_por_python_jose_sigue_valiendo(
    monkeypatch: pytest.MonkeyPatch, token: str, esperado: dict[str, Any]
) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", CLAVE_LARGA)

    payload = security.decode_token(token)

    # Igualdad exacta: ni un claim de mas ni de menos. ``==`` no distingue
    # True de 1, asi que el bool se mira aparte; ``store_id`` null llega como
    # ``None`` (la igualdad ya exige la clave presente).
    assert payload == esperado
    assert type(payload["is_global_admin"]) is bool


def test_el_token_nuevo_tiene_la_misma_forma_que_el_de_python_jose() -> None:
    token = security.create_access_token(
        {
            "sub": "u1",
            "sid": "s1",
            "store_id": None,
            "role": "super_admin",
            "is_global_admin": True,
        }
    )

    cabecera = jwt.get_unverified_header(token)
    assert cabecera == {"alg": "HS256", "typ": "JWT"}
    payload = security.decode_token(token)
    assert set(payload) == {
        "sub",
        "sid",
        "store_id",
        "role",
        "is_global_admin",
        "exp",
        "iat",
        "jti",
        "iss",
        "aud",
    }
    assert payload["store_id"] is None and payload["is_global_admin"] is True
    # Enteros (segundos), como los ponia python-jose: no floats ni ISO.
    assert isinstance(payload["exp"], int) and isinstance(payload["iat"], int)
    assert payload["exp"] - payload["iat"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


# --- ALGORITHM fijo en la configuracion -------------------------------------


@pytest.mark.parametrize("alg", ["HS512", "RS256", "none", ""])
def test_un_algoritmo_distinto_de_hs256_no_carga_la_config(
    monkeypatch: pytest.MonkeyPatch, alg: str
) -> None:
    """Un ALGORITHM mal puesto en el entorno corta el arranque (regla 21) en
    vez de volver 500 cada login al primer ``jwt.encode``."""
    monkeypatch.setenv("ALGORITHM", alg)

    with pytest.raises(ValidationError, match="ALGORITHM"):
        # Como core/config.py::_load_settings: el resto sale del entorno.
        Settings()  # type: ignore[call-arg]


# --- todo token malo es InvalidTokenError (401, nunca 500) -------------------


def test_token_vencido() -> None:
    token = security.create_access_token(
        {"sub": "u1", "sid": "s1"}, expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_token(token)
    assert issubclass(jwt.ExpiredSignatureError, jwt.InvalidTokenError)


def test_firma_con_otra_clave() -> None:
    token = _firmar(_claims(), "otra-clave-de-atacante-0123456789abcdef")
    with pytest.raises(jwt.InvalidSignatureError):
        security.decode_token(token)


def test_firma_alterada() -> None:
    cabecera, cuerpo, _ = _firmar(_claims()).split(".")
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(f"{cabecera}.{cuerpo}.{'A' * 43}")


@pytest.mark.parametrize("alg", ["none", "None", "NONE"])
def test_alg_none_se_rechaza(alg: str) -> None:
    cuerpo = _b64(_claims(exp=EXP_2100, iat=IAT_PASADO))
    sin_firma = f"{_b64({'alg': alg, 'typ': 'JWT'})}.{cuerpo}."
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(sin_firma)


def test_otro_hmac_con_la_misma_clave_se_rechaza() -> None:
    """Solo HS256: un HS512 bien firmado con NUESTRA clave tampoco entra."""
    with pytest.raises(jwt.InvalidAlgorithmError):
        security.decode_token(_firmar(_claims(), alg="HS512"))


@pytest.mark.parametrize("alg", ["RS256", "ES256", "PS256", "EdDSA"])
def test_confusion_de_algoritmo_se_rechaza(alg: str) -> None:
    """Un token que dice ser asimetrico no se verifica como HMAC con la clave
    (el ataque clasico usa la clave publica como secreto HMAC)."""
    cuerpo = _b64(_claims(exp=EXP_2100, iat=IAT_PASADO))
    entrada = f"{_b64({'alg': alg, 'typ': 'JWT'})}.{cuerpo}"
    firma = hmac.new(
        settings.SECRET_KEY.encode(), entrada.encode(), hashlib.sha256
    ).digest()
    token = f"{entrada}.{base64.urlsafe_b64encode(firma).rstrip(b'=').decode()}"
    with pytest.raises(jwt.InvalidAlgorithmError):
        security.decode_token(token)


@pytest.mark.parametrize(
    ("cambios", "error"),
    [
        ({"aud": "otro-sistema"}, jwt.InvalidAudienceError),
        ({"iss": "otro-emisor"}, jwt.InvalidIssuerError),
        ({"exp": None}, jwt.MissingRequiredClaimError),
        ({"iat": None}, jwt.MissingRequiredClaimError),
        ({"aud": None}, jwt.MissingRequiredClaimError),
        ({"sub": None}, jwt.MissingRequiredClaimError),
        ({"iss": None}, jwt.MissingRequiredClaimError),
        ({"sub": 123}, jwt.exceptions.InvalidSubjectError),
        ({"jti": 123}, jwt.exceptions.InvalidJTIError),
        ({"iat": "ayer"}, jwt.InvalidIssuedAtError),
    ],
    ids=[
        "aud-ajena",
        "iss-ajeno",
        "sin-exp",
        "sin-iat",
        "sin-aud",
        "sin-sub",
        "sin-iss",
        "sub-no-string",
        "jti-no-string",
        "iat-no-numerico",
    ],
)
def test_claims_invalidos(
    cambios: dict[str, Any], error: type[jwt.InvalidTokenError]
) -> None:
    with pytest.raises(error):
        security.decode_token(_firmar(_claims(**cambios)))
    assert issubclass(error, jwt.InvalidTokenError)


def test_iat_en_el_futuro_se_rechaza() -> None:
    """Cambio de semantica respecto de python-jose, que solo exigia que
    ``iat`` fuera entero: PyJWT rechaza un ``iat`` posterior a ahora (leeway
    0). Los tokens los emite y verifica el mismo host (un solo reloj)."""
    futuro = datetime.now(timezone.utc) + timedelta(minutes=2)
    with pytest.raises(jwt.ImmatureSignatureError):
        security.decode_token(_firmar(_claims(iat=futuro)))


def test_basura_no_es_un_token() -> None:
    for basura in ("", "a.b", "a.b.c", "no-es-un-jwt", "...."):
        with pytest.raises(jwt.InvalidTokenError):
            security.decode_token(basura)
