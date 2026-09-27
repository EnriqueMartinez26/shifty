"""Criterios de la prueba de aceptacion sobre la salida de Locust (plan §9).

2026-09-24. La prueba de aceptacion (200 tiendas, 150 clientes + 45 duenos +
5 superadmin, 20 minutos de meseta) no sirve si "pasa" se decide mirando un
grafico: ``scripts/perf_acceptance_check.py`` lee el ``--csv`` de Locust, el
conteo de codigos por ruta y las muestras de ``/ops/slo`` que toma el propio
escenario, y sale distinto de cero si algo no cumple:

- p95 < 500 ms por ruta con al menos 20 muestras, y global (el login tiene su
  propio umbral: bcrypt de 12 rondas);
- cero 5xx, cero 429 y cero errores de conexion;
- cada rafaga sobre el mismo slot: 1 x 201 y el resto 409;
- atraso del outbox y de los mails < 2 min en todas las muestras del SLO, y
  cero descartes por presupuesto si la metrica existe;
- memoria de cada contenedor < 70 % si hay log de ``docker stats``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND_ROOT / "scripts" / "perf_acceptance_check.py"

CABECERA = (
    "Type,Name,Request Count,Failure Count,Median Response Time,"
    "Average Response Time,Min Response Time,Max Response Time,"
    "Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,90%,95%,98%,"
    "99%,99.9%,99.99%,100%"
)


def _modulo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("perf_acceptance_check", SCRIPT)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _fila(metodo: str, nombre: str, cuenta: int, p95: int | str) -> str:
    return (
        f"{metodo},{nombre},{cuenta},0,40,50,5,900,100,3.0,0.0,"
        f"40,45,50,55,60,{p95},{p95},{p95},{p95},{p95},{p95}"
    )


def _escribir(
    tmp: Path,
    filas: list[str],
    *,
    codigos: dict[str, Any] | None = None,
    slo: list[dict[str, Any]] | None = None,
    stats: str | None = None,
) -> list[str]:
    (tmp / "run_stats.csv").write_text(
        "\n".join([CABECERA, *filas]) + "\n", encoding="utf-8"
    )
    (tmp / "run_codigos.json").write_text(
        json.dumps(
            codigos
            if codigos is not None
            else {
                "por_ruta": {"GET /public/services": {"200": 500}},
                "rafagas": [{"201": 1, "409": 9}],
                "errores_de_conexion": 0,
            }
        ),
        encoding="utf-8",
    )
    muestras = (
        slo
        if slo is not None
        else [
            {
                "t": "2026-09-24T10:00:00Z",
                "metrics": {
                    "oldest_pending_outbox_seconds": 5,
                    "oldest_pending_email_send_seconds": 0,
                    "failed_webhooks": 0,
                },
            }
        ]
    )
    (tmp / "run_slo.jsonl").write_text(
        "".join(json.dumps(m) + "\n" for m in muestras), encoding="utf-8"
    )
    argumentos = ["--csv-prefix", str(tmp / "run")]
    if stats is not None:
        (tmp / "stats.log").write_text(stats, encoding="utf-8")
        argumentos += ["--docker-stats", str(tmp / "stats.log")]
    return argumentos


FILAS_OK = [
    _fila("GET", "/public/services", 500, 120),
    _fila("GET", "/public/availability", 800, 310),
    _fila("POST", "/auth/login", 45, 800),
    _fila("GET", "/reports/export", 3, 4000),
    _fila("", "Aggregated", 1348, 300),
]


def test_una_corrida_que_cumple_todo_pasa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argumentos = _escribir(tmp_path, FILAS_OK)

    assert _modulo().main(argumentos) == 0
    salida = capsys.readouterr().out
    assert "APROBADA" in salida


def test_una_ruta_con_p95_sobre_500_falla(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    filas = [*FILAS_OK[:-1], _fila("GET", "/dashboard/summary", 90, 620), FILAS_OK[-1]]
    argumentos = _escribir(tmp_path, filas)

    assert _modulo().main(argumentos) == 1
    salida = capsys.readouterr().out
    assert "GET /dashboard/summary" in salida and "620" in salida


def test_con_pocas_muestras_la_ruta_no_se_juzga(tmp_path: Path) -> None:
    """Menos de 20 muestras no dicen nada de un p95."""
    filas = [*FILAS_OK[:-1], _fila("PATCH", "/stores/me", 12, 900), FILAS_OK[-1]]

    assert _modulo().main(_escribir(tmp_path, filas)) == 0


def test_el_login_tiene_su_propio_umbral(tmp_path: Path) -> None:
    filas = [*FILAS_OK[:2], _fila("POST", "/auth/login", 45, 1200), FILAS_OK[-1]]

    assert _modulo().main(_escribir(tmp_path, filas)) == 1


def test_el_p95_global_tambien_cuenta(tmp_path: Path) -> None:
    filas = [*FILAS_OK[:-1], _fila("", "Aggregated", 1348, 510)]

    assert _modulo().main(_escribir(tmp_path, filas)) == 1


def test_un_runner_lejano_suma_su_latencia_de_red_al_umbral(tmp_path: Path) -> None:
    """Un runner en EE.UU. agrega 120-150 ms de ida y vuelta a Argentina."""
    filas = [*FILAS_OK[:-1], _fila("GET", "/dashboard/summary", 90, 620), FILAS_OK[-1]]
    argumentos = _escribir(tmp_path, filas)

    assert _modulo().main([*argumentos, "--network-offset-ms", "150"]) == 0


@pytest.mark.parametrize(
    ("codigos", "motivo"),
    [
        (
            {"por_ruta": {"GET /public/services": {"200": 10, "502": 1}}},
            "5xx",
        ),
        (
            {"por_ruta": {"GET /public/availability": {"200": 10, "429": 3}}},
            "429",
        ),
        (
            {"por_ruta": {}, "errores_de_conexion": 2},
            "conexion",
        ),
        (
            {"por_ruta": {}, "rafagas": [{"201": 1, "409": 9}, {"201": 2, "409": 8}]},
            "rafaga",
        ),
        (
            {"por_ruta": {}, "rafagas": [{"201": 1, "409": 8, "500": 1}]},
            "rafaga",
        ),
        (
            {"por_ruta": {}, "rafagas": [{"409": 10}]},
            "rafaga",
        ),
    ],
    ids=["5xx", "429", "conexion", "dos-ganadoras", "5xx-en-rafaga", "ninguna"],
)
def test_errores_y_rafagas(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    codigos: dict[str, Any],
    motivo: str,
) -> None:
    argumentos = _escribir(tmp_path, FILAS_OK, codigos=codigos)

    assert _modulo().main(argumentos) == 1
    assert motivo in capsys.readouterr().out.lower()


def test_los_409_fuera_de_la_rafaga_no_son_errores(tmp_path: Path) -> None:
    """Un slot tomado entre la disponibilidad y la reserva es un 409 legitimo."""
    codigos = {
        "por_ruta": {"POST /public/appointments": {"201": 40, "409": 3}},
        "rafagas": [{"201": 1, "409": 9}],
    }

    assert _modulo().main(_escribir(tmp_path, FILAS_OK, codigos=codigos)) == 0


def test_sin_rafagas_registradas_falla(tmp_path: Path) -> None:
    codigos: dict[str, Any] = {"por_ruta": {}, "rafagas": []}

    assert _modulo().main(_escribir(tmp_path, FILAS_OK, codigos=codigos)) == 1


@pytest.mark.parametrize(
    ("metricas", "esperado"),
    [
        ({"oldest_pending_outbox_seconds": 121}, 1),
        ({"oldest_pending_email_send_seconds": 300}, 1),
        ({"outbox_budget_drops": 1}, 1),
        ({"oldest_pending_outbox_seconds": 119, "outbox_budget_drops": 0}, 0),
    ],
    ids=["outbox", "mails", "descartes", "al-dia"],
)
def test_el_atraso_del_outbox_se_mide_en_cada_muestra(
    tmp_path: Path, metricas: dict[str, int], esperado: int
) -> None:
    al_dia = {
        "oldest_pending_outbox_seconds": 3,
        "oldest_pending_email_send_seconds": 0,
    }
    slo = [
        {"t": "a", "metrics": al_dia},
        {"t": "b", "metrics": {**al_dia, **metricas}},
    ]

    assert _modulo().main(_escribir(tmp_path, FILAS_OK, slo=slo)) == esperado


@pytest.mark.parametrize(
    "falta", ["oldest_pending_outbox_seconds", "oldest_pending_email_send_seconds"]
)
def test_una_muestra_sin_la_metrica_de_atraso_falla(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], falta: str
) -> None:
    """Sin la metrica no se sabe si el outbox estaba al dia: no es un 0."""
    metricas = {
        "oldest_pending_outbox_seconds": 1,
        "oldest_pending_email_send_seconds": 1,
    }
    metricas.pop(falta)
    slo = [{"t": "a", "metrics": metricas}]

    assert _modulo().main(_escribir(tmp_path, FILAS_OK, slo=slo)) == 1
    assert falta in capsys.readouterr().out


def test_una_linea_rota_del_slo_es_error_de_entrada(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argumentos = _escribir(tmp_path, FILAS_OK)
    with (tmp_path / "run_slo.jsonl").open("a", encoding="utf-8") as archivo:
        archivo.write('{"t": "b", "metrics": {\n')

    assert _modulo().main(argumentos) == 2
    assert "run_slo.jsonl" in capsys.readouterr().out


def test_sin_muestras_del_slo_no_se_aprueba(tmp_path: Path) -> None:
    assert _modulo().main(_escribir(tmp_path, FILAS_OK, slo=[])) == 1


@pytest.mark.parametrize(
    ("stats", "esperado"),
    [
        (
            "2026-09-24T10:00:00Z\tshifty-backend-1\t80.1%\t1.2GiB / 2GiB\t60.00%"
            "\t1MB / 1MB\t0B / 0B\t30\n"
            "2026-09-24T10:00:05Z\tshifty_db\t20.0%\t1GiB / 4GiB\t25.00%"
            "\t1MB / 1MB\t0B / 0B\t30\n",
            0,
        ),
        (
            "2026-09-24T10:00:00Z\tshifty-backend-1\t80.1%\t1.5GiB / 2GiB\t75.10%"
            "\t1MB / 1MB\t0B / 0B\t30\n",
            1,
        ),
        # Sin la marca de tiempo (docker stats a secas) tambien se lee.
        ("shifty_redis_cache\t1.0%\t200MiB / 256MiB\t78.13%\t0B / 0B\t0B / 0B\t5\n", 1),
    ],
    ids=["por-debajo", "sobre-70", "sin-marca"],
)
def test_la_memoria_de_cada_contenedor_queda_bajo_el_70(
    tmp_path: Path, stats: str, esperado: int
) -> None:
    assert _modulo().main(_escribir(tmp_path, FILAS_OK, stats=stats)) == esperado


def test_sin_el_csv_de_locust_sale_con_error_de_entrada(tmp_path: Path) -> None:
    assert _modulo().main(["--csv-prefix", str(tmp_path / "no-existe")]) == 2
