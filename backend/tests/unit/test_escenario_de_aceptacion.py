"""Escenario de la prueba de aceptacion: mezcla, forma de carga y conteos.

2026-09-24 (plan §9). Lo que se puede fijar sin generar carga: la mezcla de
150 clientes + 45 duenos + 5 superadmin, la rampa de 5 minutos con 20 de
meseta, el manifiesto que deja el seed y el conteo de codigos que usa
``scripts/perf_acceptance_check.py``. Se carga el modulo puro, nunca el
locustfile en pytest; se prueba en un subprocess aislado.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODULO = BACKEND_ROOT / "loadtests" / "aceptacion.py"
LOCUSTFILE = BACKEND_ROOT / "loadtests" / "locust_aceptacion.py"


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


def test_main_falla_antes_de_efectos_y_reusa_el_host_canonico(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    m = _modulo()
    salida = tmp_path / "manifiesto.json"
    origen_aprobado = "https://staging.example.com"
    api_base = f"{origen_aprobado}/api"
    valores_verificados: list[dict[str, str]] = []
    hosts_de_transporte: list[str] = []
    rutas: list[str] = []

    def verificar(environment: dict[str, str]) -> str:
        valores_verificados.append(environment)
        if environment["STAGING_URL"] == "https://other.example.com/api":
            raise m.TargetCheckError("origen rechazado")
        return api_base

    respuestas = {
        "/public/stores/cap-001": {"public_id": "S1"},
        "/public/services?store_public_id=S1": [{"public_id": "SV1"}],
        "/public/staff?store_public_id=S1": [{"public_id": "ST1"}],
    }

    def transporte(host: str, pausa_s: float) -> Callable[[str], object]:
        hosts_de_transporte.append(host)
        assert host == api_base
        assert pausa_s == pytest.approx(0.05)

        def obtener(ruta: str) -> object:
            rutas.append(ruta)
            return respuestas.get(ruta)

        return obtener

    monkeypatch.setenv("PERF_ALLOWED_ORIGIN", origen_aprobado)
    monkeypatch.setenv("PERF_ALLOW_LOCAL_TARGET", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    monkeypatch.setattr(m, "verify_target", verificar)
    monkeypatch.setattr(m, "_obtener_http", transporte)

    rechazada = m.main(
        [
            "--host",
            "https://other.example.com/api",
            "--out",
            str(salida),
            "--stores",
            "1",
        ]
    )
    assert rechazada == 1
    assert not hosts_de_transporte and not salida.exists()
    assert "Destino de staging rechazado" in capsys.readouterr().err

    resultado = m.main(
        [
            "--host",
            "https://staging.example.com/api/",
            "--out",
            str(salida),
            "--stores",
            "1",
        ]
    )

    assert resultado == 0 and hosts_de_transporte == [api_base]
    assert valores_verificados == [
        {
            "STAGING_URL": "https://other.example.com/api",
            "PERF_ALLOWED_ORIGIN": origen_aprobado,
            "PERF_ALLOW_LOCAL_TARGET": "true",
            "GITHUB_ACTIONS": "false",
        },
        {
            "STAGING_URL": "https://staging.example.com/api/",
            "PERF_ALLOWED_ORIGIN": origen_aprobado,
            "PERF_ALLOW_LOCAL_TARGET": "true",
            "GITHUB_ACTIONS": "false",
        },
    ]
    assert rutas == [
        "/public/stores/cap-001",
        "/public/services?store_public_id=S1",
        "/public/staff?store_public_id=S1",
    ]
    assert json.loads(salida.read_text(encoding="utf-8")) == {
        "stores": [
            {
                "slug": "cap-001",
                "store_public_id": "S1",
                "owner_email": "owner-001@capacidad.example.com",
                "service_ids": ["SV1"],
                "staff_ids": ["ST1"],
            }
        ]
    }


def test_obtener_http_rechaza_redirecciones_sin_abrir_otro_destino(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = _modulo()
    handlers: list[object] = []
    destinos: list[str] = []

    class AbridorFalso:
        def open(self, url: str, *, timeout: int) -> object:
            destinos.append(url)
            raise m.urllib.error.HTTPError(url, 302, "Found", {}, None)

    def crear_abridor(*recibidos: object) -> AbridorFalso:
        handlers.extend(recibidos)
        return AbridorFalso()

    monkeypatch.setattr(m.urllib.request, "build_opener", crear_abridor)
    host = "https://staging.example.com/api"
    obtener = m._obtener_http(host, pausa_s=0)

    with pytest.raises(m.urllib.error.HTTPError) as error:
        obtener("/public/stores/cap-001")

    assert error.value.code == 302
    assert destinos == [f"{host}/public/stores/cap-001"]
    handler = handlers[0]
    assert isinstance(handler, m._SinRedirecciones)
    assert (
        handler.redirect_request(None, None, 302, "Found", {}, "https://other/") is None
    )


def test_locust_sondea_staging_antes_de_cargar_manifest_en_subprocess(
    tmp_path: Path,
) -> None:
    marcador = tmp_path / "readiness-url.txt"
    script = f"""\
import importlib.util, sys
import os
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, {str(BACKEND_ROOT)!r})
import locust
import scripts.verify_perf_target as verifier
worker = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.stdin.read(),encoding='utf-8')"
verifier._probe_worker_command = lambda: [sys.executable, "-c", worker, {str(marcador)!r}]
spec = importlib.util.spec_from_file_location("locust_aceptacion", {str(LOCUSTFILE)!r})
assert spec and spec.loader
acceptance = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = acceptance
spec.loader.exec_module(acceptance)
request_options = []
request_failures = []
class FakeResponse:
    status_code = 302
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def success(self): pass
    def failure(self, message): request_failures.append(message)
class FakeClient:
    def request(self, _method, _url, **kwargs):
        request_options.append(kwargs)
        return FakeResponse()
acceptance._pedir(FakeClient(), "GET", "/redirect", name="/redirect")
assert request_options[0]["allow_redirects"] is False
assert request_failures == ["HTTP 302"]
expected = "https://staging.example.com/api/ops/health/ready"
loaded = []
def cargar(path):
    assert Path({str(marcador)!r}).read_text(encoding="utf-8") == expected
    loaded.append(str(path))
    return []
acceptance.cargar_manifiesto = cargar
environment = SimpleNamespace(host="https://staging.example.com/api/")
acceptance._validar(environment)
assert environment.host.endswith("/api") and loaded == ["manifiesto-de-prueba.json"]
verifier._probe_worker_command = lambda: [sys.executable, "-c", "import sys; sys.stdin.read(); sys.exit(1)"]
try:
    acceptance._validar(SimpleNamespace(host="https://staging.example.com/api/"))
except SystemExit as exc:
    assert "Destino de Locust rechazado" in str(exc)
else:
    raise AssertionError("Locust aceptó una readiness fallida")
assert loaded == ["manifiesto-de-prueba.json"]
try:
    acceptance._validar(SimpleNamespace(host="http://localhost/api"))
except SystemExit as exc:
    assert "Destino de Locust rechazado" in str(exc)
else:
    raise AssertionError("Locust aceptó loopback en GitHub Actions")
assert loaded == ["manifiesto-de-prueba.json"]
request_options = []
class FakeSloResponse:
    status_code = 200
    ok = True
    def __init__(self, data): self.data = data
    def json(self): return self.data
class FakeSloSession:
    def post(self, url, **kwargs):
        request_options.append(("POST", url, kwargs))
        return FakeSloResponse({{"success": True, "data": {{"access_token": "token"}}}})
    def get(self, url, **kwargs):
        request_options.append(("GET", url, kwargs))
        return FakeSloResponse({{"success": True, "data": {{"status": "ok", "metrics": {{}}}}}})
acceptance.requests.Session = FakeSloSession
class StopSampling(Exception): pass
def detener(_seconds): raise StopSampling()
acceptance.gevent = SimpleNamespace(sleep=detener)
os.chdir({str(tmp_path)!r})
try:
    acceptance._muestrear_slo(SimpleNamespace(host="https://staging.example.com/api", parsed_options=None))
except StopSampling:
    pass
else:
    raise AssertionError("el sondeo SLO no alcanzó el sleep de su ciclo")
assert [call[2]["allow_redirects"] for call in request_options] == [False, False]
assert request_options[0][0:2] == ("POST", "https://staging.example.com/api/auth/login")
assert request_options[1][0:2] == ("GET", "https://staging.example.com/api/ops/slo")
"""
    entorno = os.environ.copy()
    entorno.update(
        {
            "PERF_ALLOWED_ORIGIN": "https://staging.example.com",
            "SHIFTY_MANIFEST": "manifiesto-de-prueba.json",
            "SEED_OWNER_PASSWORD": "prueba",
            "SHIFTY_SUPERADMIN_EMAIL": "admin@example.com",
            "SHIFTY_SUPERADMIN_PASSWORD": "prueba",
            "GITHUB_ACTIONS": "true",
            "PERF_ALLOW_LOCAL_TARGET": "true",
        }
    )

    proceso = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
        ],
        cwd=BACKEND_ROOT,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert proceso.returncode == 0, (
        f"stdout:\n{proceso.stdout}\nstderr:\n{proceso.stderr}"
    )


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
