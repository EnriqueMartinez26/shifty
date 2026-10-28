"""Escenario de la prueba de aceptacion: mezcla, forma de carga y conteos.

2026-09-24 (plan §9). Lo que se puede fijar sin generar carga: la mezcla de
150 clientes + 45 duenos + 5 superadmin, la rampa de 5 minutos con 20 de
meseta, el manifiesto que deja el seed y el conteo de codigos que usa
``scripts/perf_acceptance_check.py``. Se carga el modulo puro, nunca el
locustfile: importar ``locust`` parchea el proceso con gevent.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import subprocess
import sys
import threading
import urllib.error
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest
import requests
from requests.adapters import BaseAdapter

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODULO = BACKEND_ROOT / "loadtests" / "aceptacion.py"
LOCUSTFILE = BACKEND_ROOT / "loadtests" / "locust_aceptacion.py"


class _Adapter(BaseAdapter):
    def __init__(self, status: int, location: str | None = None) -> None:
        self.status = status
        self.location = location
        self.requests: list[requests.PreparedRequest] = []

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float | None, float | None] | None = None,
        verify: bool | str = True,
        cert: str | tuple[str, str] | None = None,
        proxies: dict[str, str] | None = None,
    ) -> requests.Response:
        del stream, timeout, verify, cert, proxies
        self.requests.append(request)
        response = requests.Response()
        response.status_code = self.status
        response.url = request.url or ""
        response.request = request
        response._content = b"{}"
        if self.location:
            response.headers["Location"] = self.location
        return response

    def close(self) -> None:
        pass


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("aceptacion", MODULO)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_la_mezcla_es_la_del_plan() -> None:
    m = _modulo()
    assert (m.CLIENTES, m.DUENOS, m.SUPERADMINS) == (150, 45, 5)
    assert m.TOTAL_USUARIOS == 200
    assert (m.RAMPA_S, m.MESETA_S) == (300, 1200)
    assert (m.RAFAGA_CADA_S, m.RAFAGA_TAMANO) == (300, 10)


def test_cli_rechaza_destino_remoto_antes_de_consultar_o_escribir_manifiesto(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    m = _modulo()
    salida = tmp_path / "manifiesto.json"
    monkeypatch.setattr(
        m,
        "manifiesto_desde_api",
        lambda *_args, **_kwargs: pytest.fail("no debe consultar la API"),
    )

    resultado = m.main(
        [
            "--host",
            "https://production.example.test/api",
            "--stores",
            "1",
            "--out",
            str(salida),
        ],
        target_environment={"PERF_ALLOWED_ORIGIN": "https://staging.example.test"},
    )

    assert resultado == 1
    assert "no coincide con el origen aprobado" in capsys.readouterr().err
    assert not salida.exists()


def test_cli_real_importa_el_guard_canonico_y_rechaza_antes_de_escribir(
    tmp_path: Path,
) -> None:
    salida = tmp_path / "manifiesto.json"
    environment = os.environ.copy()
    environment["PERF_ALLOWED_ORIGIN"] = "https://staging.example.test"
    resultado = subprocess.run(
        [
            sys.executable,
            str(BACKEND_ROOT / "loadtests" / "aceptacion.py"),
            "--host",
            "https://production.example.test/api",
            "--stores",
            "1",
            "--out",
            str(salida),
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert resultado.returncode == 1
    assert "Destino de rendimiento rechazado" in resultado.stderr
    assert "no coincide con el origen aprobado" in resultado.stderr
    assert not salida.exists()


def test_cli_usa_el_api_base_canonico_que_valido_el_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = _modulo()
    salida = tmp_path / "manifiesto.json"
    bases: list[str] = []

    def obtener_http(host: str, _pausa: float) -> Callable[[str], object]:
        bases.append(host)
        return lambda _ruta: None

    monkeypatch.setattr(m, "_obtener_http", obtener_http)
    monkeypatch.setattr(
        m, "manifiesto_desde_api", lambda *_args, **_kwargs: {"stores": [{}]}
    )

    resultado = m.main(
        [
            "--host",
            "http://127.0.0.1:8080/api/",
            "--local-rehearsal",
            "--stores",
            "1",
            "--out",
            str(salida),
        ],
        target_environment={},
    )

    assert resultado == 0
    assert bases == ["http://127.0.0.1:8080/api"]
    assert json.loads(salida.read_text(encoding="utf-8")) == {"stores": [{}]}


def _locust_run(
    host: str, *, manifest: str, local_rehearsal: bool = False
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PERF_ALLOWED_ORIGIN": "https://staging.example.test",
            "SHIFTY_MANIFEST": manifest,
            "SEED_OWNER_PASSWORD": "test-password",
            "SHIFTY_SUPERADMIN_EMAIL": "admin@example.test",
            "SHIFTY_SUPERADMIN_PASSWORD": "test-password",
        }
    )
    command = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(LOCUSTFILE),
        "--headless",
        "--users",
        "1",
        "--spawn-rate",
        "1",
        "--run-time",
        "1s",
        "--host",
        host,
    ]
    if local_rehearsal:
        command.append("--local-rehearsal")
    return subprocess.run(
        command,
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_locust_rechaza_origen_no_aprobado_antes_de_leer_el_manifiesto(
    tmp_path: Path,
) -> None:
    resultado = _locust_run(
        "https://production.example.test/api", manifest=str(tmp_path / "missing.json")
    )
    salida = resultado.stdout + resultado.stderr

    assert resultado.returncode != 0
    assert "Destino de rendimiento rechazado" in salida
    assert "no coincide con el origen aprobado" in salida
    assert "FileNotFoundError" not in salida


def test_locust_conserva_loopback_http_solo_para_ensayo_local(tmp_path: Path) -> None:
    resultado = _locust_run(
        "http://127.0.0.1:8080/api/",
        manifest=str(tmp_path / "missing.json"),
        local_rehearsal=True,
    )
    salida = resultado.stdout + resultado.stderr

    assert resultado.returncode != 0
    assert "Destino de rendimiento rechazado" not in salida
    assert "SHIFTY_MANIFEST" in salida or "FileNotFoundError" in salida


def test_locust_rechaza_loopback_http_sin_modo_local_explicito(tmp_path: Path) -> None:
    resultado = _locust_run(
        "http://127.0.0.1:8080/api/", manifest=str(tmp_path / "missing.json")
    )
    salida = resultado.stdout + resultado.stderr

    assert resultado.returncode != 0
    assert "Destino de rendimiento rechazado" in salida
    assert "debe usar HTTPS" in salida
    assert "FileNotFoundError" not in salida


def test_la_forma_sube_en_cinco_minutos_y_corta_al_final_de_la_meseta() -> None:
    m = _modulo()

    usuarios, ritmo = m.forma_de_carga(0)
    assert usuarios == 200
    assert ritmo * 300 == pytest.approx(200), "200 usuarios en 300 s"
    assert m.forma_de_carga(1499) == (200, pytest.approx(200 / 300))
    assert m.forma_de_carga(1500) is None


def test_el_locustfile_usa_la_mezcla_y_no_importa_locust_en_el_modulo_puro() -> None:
    texto = LOCUSTFILE.read_text(encoding="utf-8")
    for peso in ("weight = CLIENTES", "weight = DUENOS", "weight = SUPERADMINS"):
        assert peso in texto
    assert "LoadTestShape" in texto
    assert "reset_all()" in texto, "el p95 se juzga en la meseta, no en la rampa"
    # Sin superadmin no hay muestras del SLO: se corta al arrancar, no al final.
    validar = texto[texto.index("def _validar") : texto.index("class ClientePublico")]
    for variable in (
        "SHIFTY_MANIFEST",
        "SEED_OWNER_PASSWORD",
        "SHIFTY_SUPERADMIN_EMAIL",
        "SHIFTY_SUPERADMIN_PASSWORD",
    ):
        assert variable in validar, variable
    assert "import locust" not in MODULO.read_text(encoding="utf-8")
    assert "from locust" not in MODULO.read_text(encoding="utf-8")


def test_todos_los_clientes_locust_pasan_por_la_politica_sin_redirects() -> None:
    texto = LOCUSTFILE.read_text(encoding="utf-8")

    assert texto.count("solicitar_sin_redirecciones(") >= 4
    assert "client.request(" not in texto
    assert "sondeo.get(" not in texto
    assert "sesion.post(" not in texto
    assert "sesion.get(" not in texto
    assert "raise StopUser()" in texto


def test_cualquier_respuesta_3xx_se_clasifica_como_redirect_rechazable() -> None:
    m = _modulo()

    assert m.es_redireccion(307)
    assert m.es_redireccion(308)
    assert m.es_redireccion(399)
    assert not m.es_redireccion(200)
    assert not m.es_redireccion(None)


def test_el_manifiesto_trae_tiendas_sin_contrasenas(tmp_path: Path) -> None:
    manifiesto = tmp_path / "manifiesto.json"
    manifiesto.write_text(
        json.dumps(
            {
                "stores": [
                    {
                        "slug": "cap-001",
                        "store_public_id": "S1",
                        "owner_email": "owner-001@capacidad.example.com",
                        "service_ids": ["SV1", "SV2"],
                        "staff_ids": ["ST1"],
                    },
                    {
                        "slug": "cap-002",
                        "store_public_id": "S2",
                        "owner_email": "owner-002@capacidad.example.com",
                        "service_ids": [],
                        "staff_ids": ["ST2"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    tiendas = _modulo().cargar_manifiesto(manifiesto)

    assert [t.slug for t in tiendas] == ["cap-001"], "sin servicios no se reserva"
    assert tiendas[0].service_ids == ("SV1", "SV2")


def test_un_manifiesto_vacio_se_rechaza(tmp_path: Path) -> None:
    manifiesto = tmp_path / "vacio.json"
    manifiesto.write_text('{"stores": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="manifiesto"):
        _modulo().cargar_manifiesto(manifiesto)


def test_las_fechas_son_distintas_y_dentro_de_los_14_dias() -> None:
    fechas = _modulo().fechas_de_consulta(
        date(2026, 9, 24), random.Random(1), cantidad=4
    )

    assert len(set(fechas)) == 4
    assert all("2026-09-25" <= f <= "2026-10-08" for f in fechas)


def test_solo_se_reserva_un_slot_disponible() -> None:
    m = _modulo()
    slots = [
        {"starts_at": "a", "status": "booked"},
        {"starts_at": "b", "status": "available"},
        {"starts_at": "c", "status": "blocked"},
    ]

    assert m.slot_libre(slots, random.Random(0))["starts_at"] == "b"
    assert m.slot_libre(slots[:1], random.Random(0)) is None


def test_el_conteo_separa_rutas_conexiones_y_rafagas() -> None:
    conteo = _modulo().ConteoDeCodigos()
    conteo.registrar("GET", "/public/services", 200)
    conteo.registrar("GET", "/public/services", 200)
    conteo.registrar("POST", "/public/appointments", 409)
    conteo.registrar("GET", "/public/staff", 0)
    conteo.registrar_rafaga([201, 409, 409, None])

    assert conteo.como_dict() == {
        "por_ruta": {
            "GET /public/services": {"200": 2},
            "POST /public/appointments": {"409": 1},
        },
        "errores_de_conexion": 1,
        "rafagas": [{"201": 1, "409": 2, "0": 1}],
    }


def test_se_desenvuelve_la_respuesta_canonica_de_la_api() -> None:
    """Fuera de los tests la API responde ``{"success": ..., "data": ...}``.

    El ensayo del 2026-09-24 lo mostro: sin desenvolver, el token del login
    no aparecia (todo el panel en 401) y la disponibilidad no traia slots.
    """
    m = _modulo()

    assert m.datos_de({"success": True, "data": {"access_token": "t"}}) == {
        "access_token": "t"
    }
    assert m.datos_de({"success": True, "data": [{"status": "available"}]}) == [
        {"status": "available"}
    ]
    assert m.datos_de([1, 2]) == [1, 2], "una respuesta cruda pasa igual"
    assert m.datos_de({"access_token": "t"}) == {"access_token": "t"}


@pytest.mark.parametrize("codigo", [307, 308])
def test_cliente_no_reenvia_cuerpo_ni_credenciales_a_un_redirect_cross_origin(
    codigo: int,
) -> None:
    m = _modulo()
    staging = _Adapter(codigo, "https://production.example.test/api/login")
    produccion = _Adapter(200)
    with requests.Session() as sesion:
        sesion.mount("https://staging.example.test/", staging)
        sesion.mount("https://production.example.test/", produccion)

        respuesta = m.solicitar_sin_redirecciones(
            sesion,
            "POST",
            "https://staging.example.test/api/login",
            headers={"Authorization": "Bearer staging-token"},
            json={"password": "staging-password"},
            allow_redirects=True,
        )

    assert respuesta.status_code == codigo
    assert len(staging.requests) == 1
    assert staging.requests[0].headers["Authorization"] == "Bearer staging-token"
    assert "staging-password" in str(staging.requests[0].body)
    assert produccion.requests == [], "el cuerpo y el token no salen a produccion"


@pytest.mark.parametrize("codigo", [307, 308])
def test_el_manifiesto_falla_sin_seguir_redirect_cross_origin(codigo: int) -> None:
    class HandlerDestino(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.server.visitas += 1  # type: ignore[attr-defined]
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            pass

    destino = ThreadingHTTPServer(("127.0.0.1", 0), HandlerDestino)
    destino.visitas = 0  # type: ignore[attr-defined]
    ubicacion = f"http://127.0.0.1:{destino.server_port}/credenciales"

    class HandlerStaging(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.server.visitas += 1  # type: ignore[attr-defined]
            self.send_response(codigo)
            self.send_header("Location", ubicacion)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            pass

    staging = ThreadingHTTPServer(("127.0.0.1", 0), HandlerStaging)
    staging.visitas = 0  # type: ignore[attr-defined]
    servidores = (staging, destino)
    hilos = [threading.Thread(target=s.serve_forever, daemon=True) for s in servidores]
    for hilo in hilos:
        hilo.start()

    try:
        m = _modulo()
        obtener = m._obtener_http(f"http://127.0.0.1:{staging.server_port}/api", 0)
        with pytest.raises(urllib.error.HTTPError) as error:
            obtener("/public/stores/cap-001")

        assert error.value.code == codigo
        assert staging.visitas == 1  # type: ignore[attr-defined]
        assert destino.visitas == 0  # type: ignore[attr-defined]
    finally:
        for servidor in servidores:
            servidor.shutdown()
            servidor.server_close()
        for hilo in hilos:
            hilo.join(timeout=2)


def test_el_manifiesto_se_arma_desde_la_api_publica_de_staging() -> None:
    """CI no tiene el archivo del seed: lo reconstruye por slug ``cap-NNN``."""
    m = _modulo()
    pedidos: list[str] = []
    respuestas = {
        "/public/stores/cap-001": {"success": True, "data": {"public_id": "S1"}},
        "/public/services?store_public_id=S1": {
            "success": True,
            "data": [{"public_id": "SV1"}, {"public_id": "SV2"}],
        },
        "/public/staff?store_public_id=S1": {
            "success": True,
            "data": [{"public_id": "ST1"}],
        },
        # cap-002 no existe (404): se saltea.
    }

    def obtener(ruta: str) -> object:
        pedidos.append(ruta)
        return respuestas.get(ruta)

    manifiesto = m.manifiesto_desde_api(
        obtener, tiendas=2, dominio="capacidad.example.com"
    )

    assert manifiesto["stores"] == [
        {
            "slug": "cap-001",
            "store_public_id": "S1",
            "owner_email": "owner-001@capacidad.example.com",
            "service_ids": ["SV1", "SV2"],
            "staff_ids": ["ST1"],
        }
    ]
    assert "/public/stores/cap-002" in pedidos
    assert not any("cap-002" in p and "services" in p for p in pedidos)
