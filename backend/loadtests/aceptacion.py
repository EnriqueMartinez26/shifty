"""Piezas puras del escenario de aceptacion (plan §9, plan-capacidad §5).

Sin Locust a proposito: importar ``locust`` parchea todo con gevent
(``monkey.patch_all``) y rompe cualquier proceso asyncio que lo cargue, asi
que lo que se puede probar sin generar carga vive aca y los tests unitarios
lo importan sin riesgo. ``locust_aceptacion.py`` es el que arma los usuarios.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# Mezcla de la prueba: 200 usuarios concurrentes.
CLIENTES = 150
DUENOS = 45
SUPERADMINS = 5
TOTAL_USUARIOS = CLIENTES + DUENOS + SUPERADMINS
# Rampa de 5 minutos y meseta de 20: cubre 4 ciclos del TTL de 5 min del
# cache de disponibilidad, varios ciclos de beat y un refresh del token de
# 15 minutos. Las estadisticas se reinician al entrar en la meseta.
RAMPA_S = 300
MESETA_S = 1200
# Rafaga sobre el mismo slot (CLAUDE.md §4): cada 5 minutos, 10 a la vez.
RAFAGA_CADA_S = 300
RAFAGA_TAMANO = 10
# Muestreo de /ops/slo durante la corrida.
SLO_CADA_S = 30


@dataclass(frozen=True)
class TiendaSembrada:
    slug: str
    store_public_id: str
    owner_email: str
    service_ids: tuple[str, ...]
    staff_ids: tuple[str, ...]


def cargar_manifiesto(path: str | Path) -> list[TiendaSembrada]:
    """Tiendas del manifiesto que escribe ``scripts/seed_capacidad.py``."""
    datos = json.loads(Path(path).read_text(encoding="utf-8"))
    tiendas = [
        TiendaSembrada(
            slug=str(t["slug"]),
            store_public_id=str(t["store_public_id"]),
            owner_email=str(t["owner_email"]),
            service_ids=tuple(str(s) for s in t["service_ids"]),
            staff_ids=tuple(str(s) for s in t["staff_ids"]),
        )
        for t in datos.get("stores", [])
    ]
    utiles = [t for t in tiendas if t.service_ids and t.staff_ids]
    if not utiles:
        raise ValueError(
            f"{path}: el manifiesto no tiene tiendas con servicios y profesionales"
        )
    return utiles


def forma_de_carga(
    tiempo_s: float,
    *,
    total: int = TOTAL_USUARIOS,
    rampa_s: int = RAMPA_S,
    meseta_s: int = MESETA_S,
) -> tuple[int, float] | None:
    """(usuarios, ritmo de alta por segundo) o ``None`` para terminar.

    Un solo objetivo con ritmo ``total / rampa`` da la rampa lineal; al final
    de la meseta la corrida termina (los criterios se juzgan en la meseta).
    """
    if tiempo_s >= rampa_s + meseta_s:
        return None
    return total, total / rampa_s


def fechas_de_consulta(
    hoy: date, rng: random.Random, *, cantidad: int, horizonte_dias: int = 14
) -> list[str]:
    """``cantidad`` fechas distintas entre manana y ``hoy + horizonte``."""
    dias = rng.sample(range(1, horizonte_dias + 1), k=min(cantidad, horizonte_dias))
    return [(hoy + timedelta(days=d)).isoformat() for d in sorted(dias)]


def datos_de(cuerpo: Any) -> Any:
    """Contenido de la respuesta canonica ``{"success": ..., "data": ...}``.

    Fuera de los tests la API envuelve todo (``core/responses.py``); el
    header ``x-raw-response`` se ignora en produccion, asi que el escenario
    no lo usa.
    """
    if isinstance(cuerpo, dict) and "success" in cuerpo and "data" in cuerpo:
        return cuerpo["data"]
    return cuerpo


def slot_libre(
    slots: Iterable[Mapping[str, Any]], rng: random.Random
) -> Mapping[str, Any] | None:
    """Un slot ``available`` al azar de la respuesta de disponibilidad."""
    libres = [s for s in slots if s.get("status") == "available"]
    return rng.choice(libres) if libres else None


class ConteoDeCodigos:
    """Codigos HTTP por ruta y resultado de cada rafaga, para el veredicto."""

    def __init__(self) -> None:
        self.por_ruta: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.errores_de_conexion = 0
        self.rafagas: list[dict[str, int]] = []

    def registrar(self, metodo: str, nombre: str, codigo: int | None) -> None:
        if not codigo:
            self.errores_de_conexion += 1
            return
        self.por_ruta[f"{metodo} {nombre}"][str(codigo)] += 1

    def registrar_rafaga(self, codigos: Iterable[int | None]) -> None:
        cuenta: dict[str, int] = defaultdict(int)
        for codigo in codigos:
            cuenta[str(codigo or 0)] += 1
        self.rafagas.append(dict(cuenta))

    def como_dict(self) -> dict[str, Any]:
        return {
            "por_ruta": {r: dict(c) for r, c in sorted(self.por_ruta.items())},
            "errores_de_conexion": self.errores_de_conexion,
            "rafagas": list(self.rafagas),
        }
