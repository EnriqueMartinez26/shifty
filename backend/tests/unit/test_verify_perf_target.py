from __future__ import annotations

import asyncio
import gzip
import json
import socket
import sys
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from scripts import verify_perf_target as module

STAGING_URL = "https://staging.example.test/api/"
ALLOWED_ORIGIN = "https://staging.example.test"
READY = json.dumps({"success": True, "data": {"environment": "staging"}}).encode()


class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.response.stream, httpx.AsyncByteStream):
            stream = self.response.stream
        else:
            stream = _ByteBody(self.response.content)
        return httpx.Response(
            self.response.status_code, headers=self.response.headers, stream=stream
        )

    async def aclose(self) -> None:
        return None


class _ByteBody(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.content

    async def aclose(self) -> None:
        return None


class _SlowBody(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        for start in range(0, len(READY), 16):
            yield READY[start : start + 16]
            await asyncio.sleep(0.02)

    async def aclose(self) -> None:
        return None


def test_validates_exact_https_origin_and_canonical_staging_readiness() -> None:
    transport = _MockTransport(httpx.Response(200, content=READY))

    api_base = module.verify_target(
        {"STAGING_URL": STAGING_URL, "PERF_ALLOWED_ORIGIN": ALLOWED_ORIGIN},
        transport=transport,
    )

    assert api_base == "https://staging.example.test/api"
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert str(request.url) == f"{api_base}/ops/health/ready"
    assert request.headers["accept"] == "application/json"
    assert request.headers["accept-encoding"] == "identity"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost/api", "http://localhost/api"),
        ("http://localhost/api/", "http://localhost/api"),
        ("http://localhost", "http://localhost"),
        ("http://localhost/", "http://localhost"),
        ("http://localhost:80/api", "http://localhost/api"),
        ("http://localhost:8000/", "http://localhost:8000"),
        ("http://127.0.0.1/api", "http://127.0.0.1/api"),
        ("http://127.0.0.1/api/", "http://127.0.0.1/api"),
        ("http://127.0.0.1", "http://127.0.0.1"),
        ("http://127.0.0.1:8000/api", "http://127.0.0.1:8000/api"),
        ("http://[::1]/api", "http://[::1]/api"),
        ("http://[::1]/api/", "http://[::1]/api"),
        ("http://[::1]/", "http://[::1]"),
        ("http://[::1]:8000", "http://[::1]:8000"),
    ],
)
def test_acepta_y_canoniza_solo_loopback_literal_local(url: str, expected: str) -> None:
    transport = _MockTransport(httpx.Response(200, content=READY))

    assert (
        module.verify_target(
            {"STAGING_URL": url, "PERF_ALLOW_LOCAL_TARGET": "true"},
            transport=transport,
        )
        == expected
    )
    assert transport.requests == []


@pytest.mark.parametrize("url", ["http://localhost/api", "http://127.0.0.1/api"])
def test_rechaza_loopback_sin_optin_local(url: str) -> None:
    with pytest.raises(
        module.TargetCheckError, match="requiere PERF_ALLOW_LOCAL_TARGET"
    ):
        module.verify_target({"STAGING_URL": url})


@pytest.mark.parametrize("github_actions", ["true", "TRUE"])
def test_rechaza_loopback_en_github_actions_aunque_haya_optin(
    github_actions: str,
) -> None:
    with pytest.raises(
        module.TargetCheckError, match="no está permitido en GitHub Actions"
    ):
        module.verify_target(
            {
                "STAGING_URL": "http://localhost/api",
                "PERF_ALLOW_LOCAL_TARGET": "true",
                "GITHUB_ACTIONS": github_actions,
            }
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://staging.example.test/api",
        "http://LOCALHOST/api",
        "http://localhost.example/api",
        "http://not-localhost/api",
        "http://internal.localhost/api",
        "http://localhost./api",
        "http://127.0.0.2/api",
        "http://127.000.0.1/api",
        "http://0177.0.0.1/api",
        "http://2130706433/api",
        "http://0x7f000001/api",
        "http://[0:0:0:0:0:0:0:1]/api",
        "http://[::ffff:127.0.0.1]/api",
        "http://localhost/other",
        "http://localhost/api/v1",
        "http://localhost/api?next=x",
        "http://localhost/api#fragment",
        "http://user@localhost/api",
        "http://localhost\\@example.test/api",
        "http://localhost:0/api",
        "http://localhost:65536/api",
        "http://localhost:abc/api",
        "http://localhost:/api",
    ],
)
def test_rechaza_loopback_no_literal_y_bypass_local(url: str) -> None:
    transport = _MockTransport(httpx.Response(200, content=READY))
    with pytest.raises(module.TargetCheckError):
        module.verify_target({"STAGING_URL": url}, transport=transport)
    with pytest.raises(module.TargetCheckError):
        module.canonical_target_url(url)
    assert transport.requests == []


def test_destino_local_rechaza_un_origen_aprobado_configurado() -> None:
    with pytest.raises(module.TargetCheckError, match="no debe configurar"):
        module.canonical_target_url("http://localhost/api", ALLOWED_ORIGIN)


def test_helper_canoniza_remoto_sin_hacer_red() -> None:
    assert module.canonical_target_url(STAGING_URL, ALLOWED_ORIGIN) == (
        "https://staging.example.test/api"
    )


def test_origin_mismatch_fails_before_probe() -> None:
    transport = _MockTransport(httpx.Response(200, content=READY))
    with pytest.raises(module.TargetCheckError, match="no coincide"):
        module.verify_target_url(
            STAGING_URL, "https://other.example.test", transport=transport
        )
    assert transport.requests == []


@pytest.mark.parametrize(
    "host",
    [
        "shifty-ar.tech",
        "www.shifty-ar.tech",
        "SHifty-AR.TECH",
    ],
)
def test_rechaza_el_dominio_de_produccion_como_origen_aprobado(host: str) -> None:
    with pytest.raises(module.TargetCheckError, match="producción"):
        module.normalize_origin(f"https://{host}")


@pytest.mark.parametrize("host", ["shifty-ar.tech", "www.shifty-ar.tech"])
def test_rechaza_el_dominio_de_produccion_como_destino_sin_consultarlo(
    host: str,
) -> None:
    transport = _MockTransport(httpx.Response(200, content=READY))
    with pytest.raises(module.TargetCheckError, match="producción"):
        module.verify_target_url(
            f"https://{host}/api", ALLOWED_ORIGIN, transport=transport
        )
    assert transport.requests == []


def test_no_bloquea_subdominios_que_pueden_ser_staging() -> None:
    assert module.normalize_origin("https://staging.shifty-ar.tech") == (
        "https://staging.shifty-ar.tech"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://staging.example.test/api",
        "https://127.0.0.1/api",
        "https://[::1]/api",
        "https://[::ffff:127.0.0.1]/api",
        "https://[::ffff:0.0.0.0]/api",
        "https://[::ffff:169.254.169.254]/api",
        "https://[::ffff:224.0.0.1]/api",
        "https://0.0.0.0/api",
        "https://169.254.1.1/api",
        "https://224.0.0.1/api",
        "https://2130706433/api",
        "https://0x7f000001/api",
        "https://localhost/api",
        "https://internal.localhost/api",
        "https://user@staging.example.test/api",
        "https://staging.example.test/other",
        "https://staging.example.test/api?next=x",
    ],
)
def test_rechaza_destinos_http_loopback_y_formas_inseguras(url: str) -> None:
    transport = _MockTransport(httpx.Response(200, content=READY))
    with pytest.raises(module.TargetCheckError):
        module.verify_target_url(url, ALLOWED_ORIGIN, transport=transport)
    assert transport.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "https://１２７.０.０.１/api",
        "https://ｌｏｃａｌｈｏｓｔ/api",
    ],
    ids=["fullwidth-loopback-ip", "fullwidth-localhost"],
)
def test_rechaza_hosts_peligrosos_tras_normalizar_idna(url: str) -> None:
    transport = _MockTransport(httpx.Response(200, content=READY))
    with pytest.raises(module.TargetCheckError):
        module.verify_target_url(url, ALLOWED_ORIGIN, transport=transport)
    assert transport.requests == []


@pytest.mark.parametrize(
    ("status", "headers", "body"),
    [
        (503, {}, READY),
        (200, {}, b'{"success":true,"data":{"environment":"production"}}'),
        (200, {}, b'{"success":false,"data":{"environment":"staging"}}'),
        (200, {}, b"not-json"),
        (302, {"Location": "https://other.example.test/"}, READY),
        (200, {"Content-Encoding": "gzip"}, gzip.compress(READY)),
        (200, {}, b"x" * (64 * 1024 + 1)),
    ],
    ids=("503", "prod", "false", "json", "302", "gzip", "size"),
)
def test_probe_rechaza_redirect_compression_y_respuesta_grande(
    status: int, headers: dict[str, str], body: bytes
) -> None:
    transport = _MockTransport(httpx.Response(status, headers=headers, content=body))
    with pytest.raises(module.TargetCheckError):
        module.verify_target_url(STAGING_URL, ALLOWED_ORIGIN, transport=transport)
    assert len(transport.requests) == 1


def test_el_probe_tiene_un_plazo_total_de_lectura(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "REQUEST_TIMEOUT_SECONDS", 0.05)
    transport = _MockTransport(httpx.Response(200, stream=_SlowBody()))

    with pytest.raises(module.TargetCheckError, match="consultar"):
        module.verify_target_url(STAGING_URL, ALLOWED_ORIGIN, transport=transport)


def test_dns_lento_no_abre_una_conexion_despues_del_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "REQUEST_TIMEOUT_SECONDS", 1)
    marker = tmp_path / "resolver-started"
    accepted = threading.Event()
    stopping = threading.Event()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.05)
    port = listener.getsockname()[1]

    def observe_connection() -> None:
        while not stopping.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            accepted.set()
            connection.close()
            return

    observer = threading.Thread(target=observe_connection, daemon=True)
    worker: threading.Thread | None = None
    try:
        observer.start()
        script = (
            "import pathlib, socket, sys, time\n"
            "from scripts import verify_perf_target as module\n"
            "marker = pathlib.Path(sys.argv[1])\n"
            "resolve = socket.getaddrinfo\n"
            "def slow_resolve(host, service, *args, **kwargs):\n"
            " marker.write_text('started', encoding='utf-8')\n"
            " time.sleep(2)\n"
            " return resolve('127.0.0.1', service, family=socket.AF_INET, "
            "type=socket.SOCK_STREAM)\n"
            "socket.getaddrinfo = slow_resolve\n"
            "raise SystemExit(module._probe_worker_main())\n"
        )
        monkeypatch.setattr(
            module,
            "_probe_worker_command",
            lambda: [sys.executable, "-c", script, str(marker)],
        )
        errors: list[Exception] = []

        def probe() -> None:
            try:
                module.probe_health(f"http://localhost:{port}/")
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=probe, daemon=True)
        worker.start()
        deadline = time.monotonic() + 3
        while not marker.exists() and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        resolver_started_at = time.monotonic()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert errors and isinstance(errors[0], module.TargetCheckError)
        time.sleep(max(0, resolver_started_at + 2.2 - time.monotonic()))
        assert not accepted.is_set()
    finally:
        stopping.set()
        listener.close()
        if observer.ident is not None:
            observer.join(timeout=1)
        if worker is not None and worker.ident is not None:
            worker.join(timeout=2)
