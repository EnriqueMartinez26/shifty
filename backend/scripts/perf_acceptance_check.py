"""Veredicto de la prueba de aceptacion sobre la salida de Locust (plan §9).

Lee lo que deja ``loadtests/locust_aceptacion.py`` corrido con
``--csv <prefijo>``:

- ``<prefijo>_stats.csv``: el CSV de Locust (p95 por ruta y global). El
  escenario reinicia las estadisticas al entrar en la meseta, asi que el p95
  es el de la carga plena, no el de la rampa.
- ``<prefijo>_codigos.json``: codigos HTTP por ruta, errores de conexion y el
  resultado de cada rafaga sobre el mismo slot.
- ``<prefijo>_slo.jsonl``: muestras de ``/ops/slo`` tomadas durante la corrida.
- ``--docker-stats``: opcional, el log de ``docker stats`` del host (mismo
  formato que ``scripts/checks.sh``, con o sin la marca de tiempo).

Criterios (plan-capacidad §5.2, plan de correccion §9):

- p95 < 500 ms por ruta con >= 20 muestras, y global. El login tiene su
  propio umbral (bcrypt de 12 rondas, p95 < 1 s); el export y las rafagas no
  entran en el p95. ``--network-offset-ms`` suma la latencia de red de un
  generador lejano (un runner en EE.UU. agrega 120-150 ms).
- 0 respuestas 5xx, 0 respuestas 429, 0 errores de conexion. Un 409 fuera de
  la rafaga es legitimo (el slot se tomo entre la disponibilidad y la reserva).
- Cada rafaga: exactamente 1 x 201 y el resto 409, sin 5xx; al menos una.
- En cada muestra del SLO: atraso del outbox y de los mails presente y
  <= 120 s y, si la metrica existe, 0 ``outbox_budget_drops``. Sin muestras,
  o con una muestra sin esas metricas, no se aprueba.
- Memoria de cada contenedor < 70 % de su limite (si hay log).

Solo stdlib: corre en el runner de CI o en la maquina del generador.
Sale 0 si aprueba, 1 si algun criterio falla y 2 si falta una entrada.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

P95_MS = 500
LOGIN_P95_MS = 1000
MIN_SAMPLES = 20
MAX_LAG_SECONDS = 120
MAX_MEM_PERCENT = 70.0
LOGIN_ROUTE = "POST /auth/login"
# Fuera del p95 por diseno: el export (probado aparte) y la rafaga, que mide
# correccion bajo contencion, no latencia.
EXCLUDED_ROUTES = re.compile(r"/reports/export|\[rafaga\]")
LAG_METRICS = ("oldest_pending_outbox_seconds", "oldest_pending_email_send_seconds")


class EntradaInvalida(Exception):
    """Falta un archivo o no tiene la forma esperada."""


@dataclass(frozen=True)
class Ruta:
    clave: str
    muestras: int
    p95: int | None


def _leer_stats(path: Path) -> tuple[list[Ruta], Ruta | None]:
    if not path.is_file():
        raise EntradaInvalida(f"no existe {path} (Locust corrio con --csv?)")
    rutas: list[Ruta] = []
    total: Ruta | None = None
    with path.open(encoding="utf-8", newline="") as archivo:
        for fila in csv.DictReader(archivo):
            try:
                crudo = fila["95%"]
                muestras = int(fila["Request Count"])
            except (KeyError, ValueError) as exc:
                raise EntradaInvalida(f"{path}: columna faltante ({exc})") from None
            p95 = int(float(crudo)) if crudo not in ("", "N/A") else None
            nombre = fila.get("Name") or ""
            metodo = (fila.get("Type") or "").strip()
            if nombre == "Aggregated" and not metodo:
                total = Ruta("global", muestras, p95)
            else:
                rutas.append(Ruta(f"{metodo} {nombre}".strip(), muestras, p95))
    return rutas, total


def _leer_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise EntradaInvalida(f"no existe {path}")
    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EntradaInvalida(f"{path}: JSON invalido ({exc})") from None
    if not isinstance(datos, dict):
        raise EntradaInvalida(f"{path}: se esperaba un objeto")
    return datos


def _leer_slo(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    muestras = []
    lineas = path.read_text(encoding="utf-8").splitlines()
    for numero, linea in enumerate(lineas, start=1):
        if not linea.strip():
            continue
        try:
            muestra = json.loads(linea)
        except json.JSONDecodeError as exc:
            raise EntradaInvalida(f"{path}:{numero}: JSON invalido ({exc})") from None
        if not isinstance(muestra, dict):
            raise EntradaInvalida(f"{path}:{numero}: se esperaba un objeto")
        muestras.append(muestra)
    return muestras


def evaluar_latencia(
    rutas: list[Ruta],
    total: Ruta | None,
    *,
    p95_ms: int,
    login_p95_ms: int,
    min_samples: int,
) -> list[str]:
    fallas = []
    for ruta in rutas:
        if EXCLUDED_ROUTES.search(ruta.clave) or ruta.p95 is None:
            continue
        if ruta.muestras < min_samples:
            continue
        umbral = login_p95_ms if ruta.clave == LOGIN_ROUTE else p95_ms
        if ruta.p95 >= umbral:
            fallas.append(
                f"p95 de {ruta.clave}: {ruta.p95} ms >= {umbral} ms "
                f"({ruta.muestras} muestras)"
            )
    if total is None or total.p95 is None:
        fallas.append("el CSV no tiene la fila Aggregated")
    elif total.p95 >= p95_ms:
        fallas.append(f"p95 global: {total.p95} ms >= {p95_ms} ms")
    return fallas


def evaluar_codigos(codigos: dict[str, Any]) -> list[str]:
    fallas = []
    por_ruta = codigos.get("por_ruta") or {}
    for ruta, conteo in sorted(por_ruta.items()):
        for codigo, cantidad in sorted((conteo or {}).items()):
            if not cantidad:
                continue
            if str(codigo).startswith("5"):
                fallas.append(f"5xx: {ruta} respondio {codigo} x{cantidad}")
            elif str(codigo) == "429":
                fallas.append(f"429: {ruta} limitado x{cantidad}")
    conexion = int(codigos.get("errores_de_conexion") or 0)
    if conexion:
        fallas.append(f"errores de conexion o timeouts: {conexion}")

    rafagas = codigos.get("rafagas") or []
    if not rafagas:
        fallas.append("rafaga: no se registro ninguna (la meseta dura menos de 5 min?)")
    for numero, rafaga in enumerate(rafagas, start=1):
        cuenta = {str(k): int(v) for k, v in (rafaga or {}).items()}
        ganadoras = cuenta.get("201", 0)
        otras = {k: v for k, v in cuenta.items() if k not in {"201", "409"} and v}
        if ganadoras != 1 or otras:
            fallas.append(
                f"rafaga {numero}: se esperaba 1 x 201 y el resto 409, hubo {cuenta}"
            )
    return fallas


def evaluar_slo(muestras: list[dict[str, Any]], *, max_lag_seconds: int) -> list[str]:
    if not muestras:
        return ["SLO: no hay muestras de /ops/slo (credenciales de superadmin?)"]
    fallas = []
    for muestra in muestras:
        metricas = muestra.get("metrics") or {}
        momento = muestra.get("t", "?")
        for clave in LAG_METRICS:
            # Sin la metrica no se sabe si estaba al dia: no vale como 0.
            if metricas.get(clave) is None:
                fallas.append(f"SLO {momento}: falta {clave} en la muestra")
                continue
            valor = int(metricas[clave])
            if valor > max_lag_seconds:
                fallas.append(f"SLO {momento}: {clave}={valor} s > {max_lag_seconds} s")
        descartes = metricas.get("outbox_budget_drops")
        if descartes:
            fallas.append(f"SLO {momento}: outbox_budget_drops={descartes}")
    return fallas


def evaluar_memoria(path: Path, *, max_percent: float) -> list[str]:
    if not path.is_file():
        raise EntradaInvalida(f"no existe {path}")
    maximos: dict[str, float] = {}
    for linea in path.read_text(encoding="utf-8").splitlines():
        campos = linea.split("\t")
        if len(campos) == 8:
            campos = campos[1:]
        if len(campos) != 7:
            continue
        nombre, porcentaje = campos[0], campos[3].strip().rstrip("%")
        try:
            valor = float(porcentaje)
        except ValueError:
            continue
        maximos[nombre] = max(valor, maximos.get(nombre, 0.0))
    return [
        f"memoria: {nombre} llego al {valor:.1f} % de su limite (>= {max_percent} %)"
        for nombre, valor in sorted(maximos.items())
        if valor >= max_percent
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv-prefix", required=True)
    parser.add_argument("--docker-stats")
    parser.add_argument("--p95-ms", type=int, default=P95_MS)
    parser.add_argument("--login-p95-ms", type=int, default=LOGIN_P95_MS)
    parser.add_argument("--min-samples", type=int, default=MIN_SAMPLES)
    parser.add_argument(
        "--network-offset-ms",
        type=int,
        default=0,
        help="latencia de red del generador a sumar a los umbrales",
    )
    parser.add_argument("--max-lag-seconds", type=int, default=MAX_LAG_SECONDS)
    parser.add_argument("--max-mem-percent", type=float, default=MAX_MEM_PERCENT)
    args = parser.parse_args(argv)

    prefijo = Path(args.csv_prefix)
    offset = max(0, args.network_offset_ms)
    try:
        rutas, total = _leer_stats(Path(f"{prefijo}_stats.csv"))
        codigos = _leer_json(Path(f"{prefijo}_codigos.json"))
        muestras = _leer_slo(Path(f"{prefijo}_slo.jsonl"))
        fallas = evaluar_latencia(
            rutas,
            total,
            p95_ms=args.p95_ms + offset,
            login_p95_ms=args.login_p95_ms + offset,
            min_samples=args.min_samples,
        )
        fallas += evaluar_codigos(codigos)
        fallas += evaluar_slo(muestras, max_lag_seconds=args.max_lag_seconds)
        if args.docker_stats:
            fallas += evaluar_memoria(
                Path(args.docker_stats), max_percent=args.max_mem_percent
            )
    except EntradaInvalida as exc:
        print(f"ERROR de entrada: {exc}")
        return 2

    juzgadas = sum(
        1
        for r in rutas
        if r.muestras >= args.min_samples and not EXCLUDED_ROUTES.search(r.clave)
    )
    print(
        f"rutas juzgadas: {juzgadas} (>= {args.min_samples} muestras), "
        f"umbral p95 {args.p95_ms + offset} ms, rafagas: "
        f"{len(codigos.get('rafagas') or [])}, muestras de SLO: {len(muestras)}"
    )
    for falla in fallas:
        print(f"FALLA {falla}")
    if fallas:
        print(f"RECHAZADA: {len(fallas)} criterio(s) sin cumplir")
        return 1
    print("APROBADA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
