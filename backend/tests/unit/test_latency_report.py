"""Reporte de latencia sobre el log JSON de nginx (F5-01, 2026-09-24).

Sin esto nadie veia la latencia en produccion (R11-12): el log de nginx no
registraba tiempos y no habia alertas. `scripts/latency_report.py` lee las
lineas JSON que agrega el formato de log de nginx (campos
`t,rid,m,u,s,rt,urt,uct,ip,ua,bytes`, `rt` en segundos), agrupa por metodo y
ruta normalizada y sale distinto de cero si una ruta con muestras suficientes
pasa el umbral de p95 o de 5xx. Solo stdlib: corre en el host, fuera de la
imagen.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND_ROOT / "scripts" / "latency_report.py"

ULID = "01J8ZQ4X7M3N5P6R8S9T0V1W2X"


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("latency_report", SCRIPT)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    # dataclasses resuelve las anotaciones buscando el modulo en sys.modules.
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _linea(
    u: str = "/public/availability",
    *,
    m: str = "GET",
    s: int | str = 200,
    rt: float | str = 0.05,
    ip: str = "203.0.113.7",
) -> str:
    return json.dumps(
        {
            "t": "2026-09-24T06:00:00+00:00",
            "rid": "abc",
            "m": m,
            "u": u,
            "s": s,
            "rt": rt,
            "urt": "0.040",
            "uct": "0.001",
            "ip": ip,
            "ua": "pytest",
            "bytes": 512,
        }
    )


# --- normalizacion de rutas -------------------------------------------------


@pytest.mark.parametrize(
    ("uri", "esperada"),
    [
        (f"/appointments/{ULID}", "/appointments/{id}"),
        (f"/api/appointments/{ULID.lower()}/confirm", "/api/appointments/{id}/confirm"),
        ("/stores/media/123", "/stores/media/{n}"),
        ("/reports/summary?from=2026-09-01&limit=6", "/reports/summary"),
        (
            "/users/3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "/users/{uuid}",
        ),
        ("/public/stores/barberia-don-juan", "/public/stores/{slug}"),
        ("/api/public/stores/otra-tienda", "/api/public/stores/{slug}"),
        # Un segmento de 26 caracteres con letras fuera de Crockford (I, L, O,
        # U) no es un ULID y queda como esta.
        ("/x/ILOUILOUILOUILOUILOUILOUIL", "/x/ILOUILOUILOUILOUILOUILOUIL"),
        ("/ops/health/ready", "/ops/health/ready"),
    ],
)
def test_normaliza_ids_numeros_y_slugs(uri: str, esperada: str) -> None:
    assert _modulo().normalize_path(uri) == esperada


# --- percentiles ------------------------------------------------------------


def test_percentil_por_rango_mas_cercano() -> None:
    modulo = _modulo()
    valores = [float(v) for v in range(1, 101)]

    assert modulo.percentile(valores, 50) == 50.0
    assert modulo.percentile(valores, 95) == 95.0
    assert modulo.percentile(valores, 99) == 99.0
    assert modulo.percentile([7.0], 99) == 7.0


def test_percentil_no_depende_del_orden_de_entrada() -> None:
    modulo = _modulo()
    assert modulo.percentile([30.0, 10.0, 20.0], 50) == 20.0


# --- lectura de lineas ------------------------------------------------------


def test_lee_rt_en_segundos_y_devuelve_milisegundos() -> None:
    muestra = _modulo().parse_line(_linea(rt="0.250", s="502"))

    assert muestra is not None
    assert muestra.rt_ms == pytest.approx(250.0)
    assert muestra.status == 502


@pytest.mark.parametrize(
    "linea",
    [
        "2026/09/24 06:00:00 [error] 29#29: *1 connect() failed",
        "{no es json",
        json.dumps({"m": "GET", "u": "/x"}),
        json.dumps(["lista"]),
        json.dumps({"m": "GET", "u": "/x", "s": 200, "rt": "-"}),
    ],
    ids=["error-log", "json-roto", "sin-campos", "no-objeto", "rt-guion"],
)
def test_ignora_lo_que_no_es_una_linea_de_acceso(linea: str) -> None:
    assert _modulo().parse_line(linea) is None


# --- reporte y umbrales -----------------------------------------------------


def _correr(lineas: list[str], *argumentos: str) -> tuple[int, str]:
    salida = io.StringIO()
    codigo = _modulo().main(
        list(argumentos), stdin=io.StringIO("\n".join(lineas)), stdout=salida
    )
    return codigo, salida.getvalue()


def _resumen(salida: str) -> dict[str, object]:
    datos = json.loads(salida.strip().splitlines()[-1])
    assert isinstance(datos, dict)
    return datos


def test_agrupa_por_metodo_y_ruta_normalizada() -> None:
    lineas = [_linea(f"/appointments/{ULID}", rt=0.01) for _ in range(5)]
    lineas += [_linea("/appointments/01J8ZQ4X7M3N5P6R8S9T0V1W2Y", rt=0.02)]
    lineas += [_linea("/appointments/{x}", m="POST", rt=0.03)]

    codigo, salida = _correr(lineas)

    assert codigo == 0
    filas = _resumen(salida)["routes"]
    assert isinstance(filas, list)
    rutas = {(r["method"], r["route"]): r for r in filas}
    assert rutas[("GET", "/appointments/{id}")]["count"] == 6
    assert ("POST", "/appointments/{x}") in rutas
    # La tabla legible sale antes del JSON.
    tabla = "\n".join(salida.strip().splitlines()[:-1])
    assert "/appointments/{id}" in tabla


def test_una_ruta_lenta_con_muestras_suficientes_sale_distinto_de_cero() -> None:
    lentas = [_linea("/dashboard", rt=0.9) for _ in range(20)]

    codigo, salida = _correr(lentas, "--p95-ms", "500")

    assert codigo == 1
    violaciones = _resumen(salida)["violations"]
    assert isinstance(violaciones, list)
    assert any("/dashboard" in v and "p95" in v for v in violaciones)


def test_una_ruta_lenta_con_pocas_muestras_no_alerta() -> None:
    codigo, _ = _correr([_linea("/dashboard", rt=0.9) for _ in range(19)])

    assert codigo == 0


def test_el_umbral_de_p95_es_configurable() -> None:
    lineas = [_linea("/dashboard", rt=0.3) for _ in range(20)]

    assert _correr(lineas, "--p95-ms", "500")[0] == 0
    assert _correr(lineas, "--p95-ms", "200")[0] == 1


def test_un_5xx_sobre_el_umbral_sale_distinto_de_cero() -> None:
    lineas = [_linea("/public/availability") for _ in range(999)]
    lineas.append(_linea("/public/availability", s=502))
    # 1 en 1000 = 0,1 %: no supera el umbral.
    assert _correr(lineas)[0] == 0

    lineas.append(_linea("/public/availability", s=503))
    codigo, salida = _correr(lineas)
    assert codigo == 1
    resumen = _resumen(salida)
    assert resumen["total_5xx"] == 2
    violaciones = resumen["violations"]
    assert isinstance(violaciones, list)
    assert any("5xx" in v for v in violaciones)


def test_un_5xx_en_una_ruta_poco_pedida_cuenta_en_el_total() -> None:
    """La tasa global tambien se mira: una ruta rara que da 500 no se esconde
    detras del minimo de muestras por ruta."""
    lineas = [_linea("/public/availability") for _ in range(100)]
    lineas.append(_linea("/reports/export", s=500))

    assert _correr(lineas)[0] == 1


def test_cuenta_ips_distintas_con_429() -> None:
    lineas = [
        _linea("/auth/login", m="POST", s=429, ip="198.51.100.1"),
        _linea("/auth/login", m="POST", s=429, ip="198.51.100.1"),
        _linea("/auth/login", m="POST", s=429, ip="198.51.100.2"),
        _linea("/auth/login", m="POST", s=200, ip="198.51.100.3"),
    ]

    _, salida = _correr(lineas)

    resumen = _resumen(salida)
    assert resumen["total_429"] == 3
    assert resumen["ips_429"] == 2


def test_sin_datos_no_alerta() -> None:
    codigo, salida = _correr(["", "2026/09/24 [notice] start worker processes"])

    assert codigo == 0
    assert _resumen(salida)["total"] == 0


def test_json_only_imprime_solo_el_resumen() -> None:
    codigo, salida = _correr([_linea()], "--json-only")

    assert codigo == 0
    assert json.loads(salida)["total"] == 1


def test_el_script_solo_usa_la_biblioteca_estandar() -> None:
    """Corre en el host con el python3 del sistema, sin el venv del backend."""
    import ast

    arbol = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    modulos = {
        alias.name.split(".")[0]
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Import)
        for alias in nodo.names
    } | {
        (nodo.module or "").split(".")[0]
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.ImportFrom) and nodo.level == 0
    }
    ajenos = {m for m in modulos if m and m not in sys.stdlib_module_names}
    assert not ajenos, f"latency_report.py importa fuera de la stdlib: {ajenos}"


def test_el_script_compila_con_el_python_del_host() -> None:
    """El host corre el python3 del sistema (Ubuntu 24.04 trae 3.12), no el 3.14
    de la imagen. `ruff format` con target py314 reescribe
    `except (A, B):` como `except A, B:` (PEP 758), que en 3.12 es un
    SyntaxError: el cron de latencia moriria sin reportar nada."""
    import ast

    ast.parse(SCRIPT.read_text(encoding="utf-8"), feature_version=(3, 10))
