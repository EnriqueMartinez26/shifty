"""Latencia y errores por ruta, leidos del log JSON de nginx (F5-01).

Uso en el host (lo corre `scripts/latency-check.sh` cada 5 minutos):

    docker compose logs --no-log-prefix --since 5m nginx \\
        | python3 backend/scripts/latency_report.py --p95-ms 500

Cada linea de acceso es un objeto JSON con los campos del `log_format` de
nginx: `t,rid,m,u,s,rt,urt,uct,ip,ua,bytes` (`rt` = `$request_time`, en
segundos). Lo que no es JSON (el error log sale por el mismo stream) se
ignora.

Agrupa por metodo y ruta normalizada (ULID -> `{id}`, UUID -> `{uuid}`,
numeros -> `{n}`, slug de tienda publica -> `{slug}`) y calcula cantidad,
p50/p95/p99 de `rt` en milisegundos y tasa de 5xx; ademas, cuantos 429 hubo y
desde cuantas IPs distintas. Imprime una tabla y, en la ultima linea, el
resumen en JSON.

Sale con 1 si una ruta con al menos `--min-samples` muestras pasa `--p95-ms`
o `--max-5xx-rate`, o si la tasa global de 5xx pasa `--max-5xx-rate`. Los
umbrales por defecto son los de aviso del plan (p95 > 500 ms, 5xx > 0,1 %).

Solo biblioteca estandar: corre con el python3 del sistema, sin el venv.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, TextIO

# ULID: 26 caracteres del alfabeto Crockford (sin I, L, O, U).
_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$", re.IGNORECASE)
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_NUMERO = re.compile(r"^\d+$")
# El slug de la vitrina publica es por tienda: sin esto cada tienda seria una
# ruta distinta y ninguna llegaria al minimo de muestras. `/api` es opcional:
# segun el log_format, `$uri` puede venir ya reescrito sin el prefijo.
_SLUG_PUBLICO = re.compile(r"^((?:/api)?/public/stores)/[^/]+$")

# Una tupla con nombre y no `except (A, B, C):` en linea: `ruff format` con
# target py314 reescribe esa forma como `except A, B, C:` (PEP 758), que el
# python3 del host (3.12 en Ubuntu 24.04) no entiende.
_CAMPO_INVALIDO = (KeyError, TypeError, ValueError)

DEFAULT_P95_MS = 500.0
DEFAULT_MAX_5XX_RATE = 0.001
DEFAULT_MIN_SAMPLES = 20


def normalize_path(uri: str) -> str:
    """Ruta sin query y con los identificadores reemplazados por su tipo."""
    path = uri.split("?", 1)[0]
    segmentos = []
    for segmento in path.split("/"):
        if _ULID.match(segmento):
            segmento = "{id}"
        elif _UUID.match(segmento):
            segmento = "{uuid}"
        elif _NUMERO.match(segmento):
            segmento = "{n}"
        segmentos.append(segmento)
    return _SLUG_PUBLICO.sub(r"\1/{slug}", "/".join(segmentos))


def percentile(values: Sequence[float], pct: float) -> float:
    """Percentil por rango mas cercano (sin interpolar): siempre un valor real."""
    if not values:
        raise ValueError("percentile de una lista vacia")
    ordenados = sorted(values)
    rango = max(1, math.ceil(pct / 100 * len(ordenados)))
    return ordenados[rango - 1]


@dataclass(frozen=True)
class Sample:
    method: str
    route: str
    status: int
    rt_ms: float
    ip: str


def parse_line(line: str) -> Sample | None:
    """Una linea de acceso de nginx, o None si no lo es."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        datos: Any = json.loads(line)
    except ValueError:
        return None
    if not isinstance(datos, dict):
        return None
    try:
        return Sample(
            method=str(datos["m"]),
            route=normalize_path(str(datos["u"])),
            status=int(datos["s"]),
            rt_ms=float(datos["rt"]) * 1000,
            ip=str(datos.get("ip", "")),
        )
    except _CAMPO_INVALIDO:
        return None


@dataclass
class RouteStats:
    method: str
    route: str
    latencies: list[float] = field(default_factory=list)
    errors_5xx: int = 0

    @property
    def count(self) -> int:
        return len(self.latencies)

    @property
    def rate_5xx(self) -> float:
        return self.errors_5xx / self.count if self.count else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "route": self.route,
            "count": self.count,
            "p50_ms": round(percentile(self.latencies, 50), 1),
            "p95_ms": round(percentile(self.latencies, 95), 1),
            "p99_ms": round(percentile(self.latencies, 99), 1),
            "errors_5xx": self.errors_5xx,
            "rate_5xx": round(self.rate_5xx, 5),
        }


@dataclass
class Report:
    routes: dict[tuple[str, str], RouteStats] = field(default_factory=dict)
    total: int = 0
    total_5xx: int = 0
    total_429: int = 0
    ips_429: set[str] = field(default_factory=set)

    def add(self, sample: Sample) -> None:
        clave = (sample.method, sample.route)
        stats = self.routes.get(clave)
        if stats is None:
            stats = self.routes[clave] = RouteStats(sample.method, sample.route)
        stats.latencies.append(sample.rt_ms)
        self.total += 1
        if 500 <= sample.status <= 599:
            stats.errors_5xx += 1
            self.total_5xx += 1
        elif sample.status == 429:
            self.total_429 += 1
            self.ips_429.add(sample.ip)


def build_report(lines: Iterable[str]) -> Report:
    report = Report()
    for line in lines:
        sample = parse_line(line)
        if sample is not None:
            report.add(sample)
    return report


def find_violations(
    report: Report, *, p95_ms: float, max_5xx_rate: float, min_samples: int
) -> list[str]:
    violaciones: list[str] = []
    for stats in report.routes.values():
        if stats.count < min_samples:
            continue
        nombre = f"{stats.method} {stats.route}"
        p95 = percentile(stats.latencies, 95)
        if p95 > p95_ms:
            violaciones.append(f"{nombre}: p95 {p95:.0f} ms > {p95_ms:.0f} ms")
        if stats.rate_5xx > max_5xx_rate:
            violaciones.append(
                f"{nombre}: 5xx {stats.rate_5xx:.2%} > {max_5xx_rate:.2%}"
            )
    if report.total:
        tasa = report.total_5xx / report.total
        if tasa > max_5xx_rate:
            violaciones.append(
                f"global: 5xx {tasa:.2%} ({report.total_5xx}/{report.total}) "
                f"> {max_5xx_rate:.2%}"
            )
    return violaciones


def summary(report: Report, violations: list[str]) -> dict[str, Any]:
    rutas = sorted(report.routes.values(), key=lambda r: (-r.count, r.route))
    return {
        "total": report.total,
        "total_5xx": report.total_5xx,
        "total_429": report.total_429,
        "ips_429": len(report.ips_429),
        "routes": [r.as_dict() for r in rutas],
        "violations": violations,
    }


def format_table(resumen: dict[str, Any]) -> str:
    encabezado = (
        f"{'metodo':<7} {'ruta':<48} {'n':>6} {'p50':>7} {'p95':>7} "
        f"{'p99':>7} {'5xx':>5}"
    )
    filas = [encabezado, "-" * len(encabezado)]
    for r in resumen["routes"]:
        filas.append(
            f"{r['method']:<7} {r['route'][:48]:<48} {r['count']:>6} "
            f"{r['p50_ms']:>7.0f} {r['p95_ms']:>7.0f} {r['p99_ms']:>7.0f} "
            f"{r['errors_5xx']:>5}"
        )
    filas.append(
        f"total={resumen['total']} 5xx={resumen['total_5xx']} "
        f"429={resumen['total_429']} ips_429={resumen['ips_429']}"
    )
    filas.extend(f"ALERTA {v}" for v in resumen["violations"])
    return "\n".join(filas)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="p50/p95/p99 y 5xx por ruta desde el log JSON de nginx (stdin)."
    )
    parser.add_argument("--p95-ms", type=float, default=DEFAULT_P95_MS)
    parser.add_argument(
        "--max-5xx-rate",
        type=float,
        default=DEFAULT_MAX_5XX_RATE,
        help="Tasa maxima de 5xx (0.001 = 0,1 %%)",
    )
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    parser.add_argument(
        "--json-only", action="store_true", help="Imprime solo el resumen JSON"
    )
    return parser.parse_args(list(argv))


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    entrada = sys.stdin if stdin is None else stdin
    salida = sys.stdout if stdout is None else stdout

    report = build_report(entrada)
    violaciones = find_violations(
        report,
        p95_ms=args.p95_ms,
        max_5xx_rate=args.max_5xx_rate,
        min_samples=args.min_samples,
    )
    resumen = summary(report, violaciones)
    if not args.json_only:
        print(format_table(resumen), file=salida)
    print(json.dumps(resumen, ensure_ascii=True), file=salida)
    return 1 if violaciones else 0


if __name__ == "__main__":
    raise SystemExit(main())
