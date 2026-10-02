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
import json
import warnings
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest
from jwt.exceptions import InvalidJTIError, InvalidSubjectError
from jwt.warnings import InsecureKeyLengthWarning

from core import security
from core.config import settings

# Clave de los tests con PyJWT: 39 bytes, sin el aviso de clave corta.
CLAVE_COMPAT = "compat-key-python-jose-0123456789abcdef"

# Emitido el 2026-10-02 por ``core.security.create_access_token`` con
# python-jose 3.5.0 (antes del cambio), con el SECRET_KEY de tests
# (CLAVE_DEL_TOKEN_DE_JOSE), iss/aud de settings y ``expires_delta`` de 70
# anios: vence en 2096.
CLAVE_DEL_TOKEN_DE_JOSE = "test-only-not-a-secret"
TOKEN_DE_PYTHON_JOSE = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIwMUo5WkNPTVBBVFVTRVIwMDAwMDAwMDAwIiwic2lkIjoiMDFKOVpDT01QQVRTRVN"
    "TSU9OMDAwMDAwMDAwIiwidHlwZSI6ImFjY2VzcyIsImV4cCI6Mzk5ODQ1NTgzMSwiaWF0IjoxNz"
    "kwOTM1ODMxLCJqdGkiOiI0NjFhMTExMS0wZDcxLTRkMzUtODAwNC00MzhhZmEyMzY4OTkiLCJpc"
    "3MiOiJzaGlmdHktYXBpIiwiYXVkIjoic2hpZnR5In0."
    "dJNR5xC80xVgVt7gHvXf4GSoCdpFAK_P4Saw3mv6W-c"
)


@pytest.fixture
def clave(monkeypatch: pytest.MonkeyPatch) -> str:
    """Clave de 39 bytes (el SECRET_KEY de tests tiene 22: PyJWT avisa)."""
    monkeypatch.setattr(settings, "SECRET_KEY", CLAVE_COMPAT)
    return CLAVE_COMPAT


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


def _firmar(claims: dict[str, Any], clave: str, alg: str = "HS256") -> str:
    return jwt.encode(claims, clave, algorithm=alg)


# --- compatibilidad con lo que emitio python-jose ---------------------------


def test_un_token_emitido_por_python_jose_sigue_valiendo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", CLAVE_DEL_TOKEN_DE_JOSE)

    payload = security.decode_token(TOKEN_DE_PYTHON_JOSE)

    assert payload["sub"] == "01J9ZCOMPATUSER0000000000"
    assert payload["sid"] == "01J9ZCOMPATSESSION000000000"
    assert payload["type"] == "access"
    assert payload["iss"] == settings.JWT_ISSUER
    assert payload["aud"] == settings.JWT_AUDIENCE
    assert payload["exp"] == 3998455831 and payload["iat"] == 1790935831


def test_el_token_nuevo_tiene_la_misma_forma_que_el_de_python_jose(
    clave: str,
) -> None:
    token = security.create_access_token({"sub": "u1", "sid": "s1"})

    cabecera = jwt.get_unverified_header(token)
    assert cabecera == {"alg": "HS256", "typ": "JWT"}
    payload = security.decode_token(token)
    assert set(payload) == {"sub", "sid", "exp", "iat", "jti", "iss", "aud"}
    # Enteros (segundos), como los ponia python-jose: no floats ni ISO.
    assert isinstance(payload["exp"], int) and isinstance(payload["iat"], int)
    assert payload["exp"] - payload["iat"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    # Al reves tambien: python-jose (o cualquier HS256) lo verificaria igual.
    assert (
        jwt.decode(
            token,
            clave,
            algorithms=["HS256"],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
        )
        == payload
    )


# --- todo token malo es InvalidTokenError (401, nunca 500) -------------------


def test_token_vencido(clave: str) -> None:
    token = security.create_access_token(
        {"sub": "u1", "sid": "s1"}, expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_token(token)
    assert issubclass(jwt.ExpiredSignatureError, jwt.InvalidTokenError)


def test_firma_con_otra_clave(clave: str) -> None:
    token = _firmar(_claims(), "otra-clave-de-atacante-0123456789abcdef")
    with pytest.raises(jwt.InvalidSignatureError):
        security.decode_token(token)


def test_firma_alterada(clave: str) -> None:
    cabecera, cuerpo, _ = _firmar(_claims(), clave).split(".")
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(f"{cabecera}.{cuerpo}.{'A' * 43}")


@pytest.mark.parametrize("alg", ["none", "None", "NONE"])
def test_alg_none_se_rechaza(clave: str, alg: str) -> None:
    sin_firma = f"{_b64({'alg': alg, 'typ': 'JWT'})}.{_b64(_claims(exp=4102444800, iat=1790000000))}."
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(sin_firma)


def test_otro_hmac_con_la_misma_clave_se_rechaza(clave: str) -> None:
    """Solo HS256: un HS512 bien firmado con NUESTRA clave tampoco entra."""
    with pytest.raises(jwt.InvalidAlgorithmError):
        security.decode_token(_firmar(_claims(), clave, alg="HS512"))


@pytest.mark.parametrize("alg", ["RS256", "ES256", "PS256", "EdDSA"])
def test_confusion_de_algoritmo_se_rechaza(clave: str, alg: str) -> None:
    """Un token que dice ser asimetrico no se verifica como HMAC con la clave
    (el ataque clasico usa la clave publica como secreto HMAC)."""
    import hashlib
    import hmac

    entrada = f"{_b64({'alg': alg, 'typ': 'JWT'})}.{_b64(_claims(exp=4102444800, iat=1790000000))}"
    firma = hmac.new(clave.encode(), entrada.encode(), hashlib.sha256).digest()
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
        ({"sub": 123}, InvalidSubjectError),
        ({"jti": 123}, InvalidJTIError),
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
    clave: str, cambios: dict[str, Any], error: type[jwt.InvalidTokenError]
) -> None:
    with pytest.raises(error):
        security.decode_token(_firmar(_claims(**cambios), clave))
    assert issubclass(error, jwt.InvalidTokenError)


def test_iat_en_el_futuro_se_rechaza(clave: str) -> None:
    """Cambio de semantica respecto de python-jose, que solo exigia que
    ``iat`` fuera entero: PyJWT rechaza un ``iat`` posterior a ahora (leeway
    0). Los tokens los emite y verifica el mismo host (un solo reloj)."""
    futuro = datetime.now(timezone.utc) + timedelta(minutes=2)
    with pytest.raises(jwt.ImmatureSignatureError):
        security.decode_token(_firmar(_claims(iat=futuro), clave))


def test_basura_no_es_un_token(clave: str) -> None:
    for basura in ("", "a.b", "a.b.c", "no-es-un-jwt", "...."):
        with pytest.raises(jwt.InvalidTokenError):
            security.decode_token(basura)


# --- lo que PyJWT hace por su cuenta (preguntas del brief) ------------------


def test_sin_verificar_firma_no_se_valida_exp_ni_aud() -> None:
    """``verify_signature=False`` apaga tambien exp y aud: solo sirve para
    leer claims (test_seguridad_sesiones), nunca para autenticar."""
    vencido = _claims(
        exp=datetime(2000, 1, 1, tzinfo=timezone.utc),
        iat=datetime(1999, 1, 1, tzinfo=timezone.utc),
        aud="otro-sistema",
    )
    token = _firmar(vencido, "cualquier-clave-de-32-bytes-o-mas!!")

    claims = jwt.decode(token, options={"verify_signature": False})

    assert claims["aud"] == "otro-sistema"


def test_clave_hmac_corta_avisa_y_la_de_produccion_no() -> None:
    """PyJWT avisa (InsecureKeyLengthWarning, no error) con una clave HS256 de
    menos de 32 bytes. Produccion exige 32 o mas (core/config.py); el SECRET_KEY
    de tests (22 bytes) solo genera el aviso."""
    with pytest.warns(InsecureKeyLengthWarning):
        jwt.encode({"sub": "x"}, "k" * 22, algorithm="HS256")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        jwt.encode({"sub": "x"}, "k" * 32, algorithm="HS256")
