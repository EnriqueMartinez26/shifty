from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from urllib.request import Request

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND_ROOT / "scripts" / "verify_perf_target.py"
STAGING_URL = "https://Staging.example.test/api/"
ALLOWED_ORIGIN = "https://staging.example.test/"


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_perf_target", SCRIPT)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


class _Response:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, size: int) -> bytes:
        return self.body[:size]


class _Opener:
    def __init__(
        self, response: _Response | None = None, error: Exception | None = None
    ):
        self.response = response or _Response(
            200,
            b'{"success":true,"data":{"environment":"staging"}}',
        )
        self.error = error
        self.request: Request | None = None
        self.timeout: int | None = None

    def open(self, request: Request, *, timeout: int) -> _Response:
        self.request = request
        self.timeout = timeout
        if self.error is not None:
            raise self.error
        return self.response


def test_builds_probe_url_from_normalized_approved_origin() -> None:
    modulo = _modulo()

    assert modulo.normalize_origin("https://STAGING.example.test:443/") == (
        "https://staging.example.test"
    )
    assert modulo.build_health_url(STAGING_URL, ALLOWED_ORIGIN) == (
        "https://staging.example.test/api/ops/health/ready"
    )
    assert (
        modulo.build_health_url("https://staging.example.test/api", ALLOWED_ORIGIN)
        == "https://staging.example.test/api/ops/health/ready"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://staging.example.test/api",
        "https://staging.example.test/",
        "https://staging.example.test/api/v1",
        "https://staging.example.test/api//",
        "https://staging.example.test/api?",
        "https://staging.example.test/api#",
        "https://user@staging.example.test/api",
        "https://user:password@staging.example.test/api",
        "https://staging.example.test:bad/api",
        "https://staging.example.test:/api",
        " https://staging.example.test/api",
        "https://staging.example.test/api\\other",
    ],
)
def test_rechaza_url_de_staging_ambigua_o_fuera_de_api(url: str) -> None:
    modulo = _modulo()
    with pytest.raises(modulo.TargetCheckError):
        modulo.build_health_url(url, ALLOWED_ORIGIN)


@pytest.mark.parametrize(
    "origin",
    [
        "http://staging.example.test",
        "https://user@staging.example.test",
        "https://staging.example.test/api",
        "https://staging.example.test?",
        "https://staging.example.test#",
        "https://staging.example.test:",
        "https://localhost",
        "https://runner.localhost",
        "https://127.0.0.1",
        "https://[::1]",
        "https://[::ffff:127.0.0.1]",
    ],
)
def test_rechaza_allowlist_que_no_es_un_origen_https(origin: str) -> None:
    modulo = _modulo()
    with pytest.raises(modulo.TargetCheckError):
        modulo.normalize_origin(origin)


@pytest.mark.parametrize(
    ("staging_url", "allowed_origin"),
    [
        ("https://other.example.test/api", ALLOWED_ORIGIN),
        ("https://staging.example.test:8443/api", ALLOWED_ORIGIN),
        (STAGING_URL, "https://other.example.test"),
    ],
)
def test_el_origen_de_staging_debe_coincidir_con_la_allowlist_normalizada(
    staging_url: str, allowed_origin: str
) -> None:
    modulo = _modulo()
    with pytest.raises(modulo.TargetCheckError):
        modulo.build_health_url(staging_url, allowed_origin)


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (302, b'{"success":true,"data":{"environment":"staging"}}'),
        (503, b'{"success":true,"data":{"environment":"staging"}}'),
        (200, b"not-json"),
        (200, b"[]"),
        (200, b'{"success":false,"data":{"environment":"staging"}}'),
        (200, b'{"success":true,"data":{}}'),
        (200, b'{"success":true,"data":{"environment":"production"}}'),
        (200, b'{"success":true,"data":{"environment":"staging"'),
    ],
)
def test_exige_http_200_y_envelope_canonico_de_staging(
    status: int, body: bytes
) -> None:
    modulo = _modulo()
    with pytest.raises(modulo.TargetCheckError):
        modulo.validate_health_response(status, body)


def test_hace_get_sin_seguir_redirecciones_y_con_timeout_acotado() -> None:
    modulo = _modulo()
    opener = _Opener()

    modulo.probe_health(
        modulo.build_health_url(STAGING_URL, ALLOWED_ORIGIN), opener=opener
    )

    assert opener.request is not None
    assert opener.request.get_method() == "GET"
    assert opener.request.full_url == (
        "https://staging.example.test/api/ops/health/ready"
    )
    assert opener.request.get_header("Accept") == "application/json"
    assert opener.timeout == 5
    assert (
        modulo._NoRedirect().redirect_request(
            None, None, 302, "Found", {}, "https://elsewhere"
        )
        is None
    )


def test_variables_faltantes_fallan_antes_de_hacer_el_get() -> None:
    opener = _Opener()

    assert _modulo().main({}, opener=opener) == 1
    assert opener.request is None


def test_origen_no_aprobado_falla_antes_de_hacer_el_get() -> None:
    opener = _Opener()

    result = _modulo().main(
        {
            "STAGING_URL": "https://production.example.test/api",
            "PERF_ALLOWED_ORIGIN": ALLOWED_ORIGIN,
        },
        opener=opener,
    )

    assert result == 1
    assert opener.request is None


def test_los_errores_no_exponen_url_ni_contenido(
    capsys: pytest.CaptureFixture[str],
) -> None:
    url_secreta = "https://private-staging-secret.example/api"
    cuerpo_secreto = "BODY-MUST-NOT-LEAK"
    opener = _Opener(error=RuntimeError(f"{url_secreta} {cuerpo_secreto}"))

    resultado = _modulo().main(
        {
            "STAGING_URL": url_secreta,
            "PERF_ALLOWED_ORIGIN": "https://private-staging-secret.example",
        },
        opener=opener,
    )

    salida = capsys.readouterr()
    assert resultado == 1
    assert url_secreta not in salida.out + salida.err
    assert cuerpo_secreto not in salida.out + salida.err
    assert "No se pudo consultar" in salida.err


def test_rechaza_respuesta_mayor_al_limite() -> None:
    modulo = _modulo()
    body = b" " * (modulo.MAX_RESPONSE_BYTES + 1)

    with pytest.raises(modulo.TargetCheckError):
        modulo.validate_health_response(200, body)
