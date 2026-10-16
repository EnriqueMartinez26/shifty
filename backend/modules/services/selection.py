"""Varios servicios del mismo profesional en UN turno: reglas puras.

Decision de Mateo (2026-10-16): un profesional puede hacer varios servicios en
un turno; profesionales distintos son turnos separados. El turno guarda el
principal (el primero elegido) en ``service_id`` y congela los demas en
``extra_services_snapshot``; su duracion y su precio son la suma.

Topes (decisiones de Mateo, 2026-10-16):

- hasta ``MAX_SERVICES_PER_APPOINTMENT`` servicios por turno (el principal +
  ``MAX_EXTRA_SERVICES``): pasarlo es 422 ``TOO_MANY_SERVICES``;
- la duracion total hasta ``MAX_TOTAL_DURATION_MINUTES`` (el tope de producto de
  un servicio, ``services/schemas.py``): pasarla es 422 ``SERVICES_TOO_LONG``.
  Ademas tiene que entrar en la jornada del profesional, como cualquier turno.

``EXTRA_SERVICES_INPUT_MAX`` es el tope DURO de la entrada (schema y query):
corta lo absurdo antes de tocar nada (regla 9) y deja que el tope de producto
salga con su propio codigo.

Sin base ni framework: lo usan el alta, la disponibilidad, las dos
reprogramaciones, el link del panel, los mails y las respuestas.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

MAX_SERVICES_PER_APPOINTMENT = 3
MAX_EXTRA_SERVICES = MAX_SERVICES_PER_APPOINTMENT - 1
EXTRA_SERVICES_INPUT_MAX = 9
MAX_TOTAL_DURATION_MINUTES = 480

# Separador de la etiqueta ("Corte + Barba") y del segmento de la clave de
# cache de la disponibilidad.
LABEL_SEPARATOR = " + "
CACHE_SEGMENT_SEPARATOR = "+"

_CENT = Decimal("0.01")


class CatalogService(Protocol):
    id: str
    public_id: str
    name: str
    duration_minutes: int
    price: Any


@dataclass(frozen=True)
class ExtraServiceLine:
    """Un servicio extra congelado en el turno."""

    service_id: str
    public_id: str
    name: str
    duration_minutes: int
    price: Decimal

    def snapshot(self) -> dict[str, str | int]:
        # Precio como texto, igual que los adicionales: el JSON de la base no
        # tiene decimales exactos.
        return {
            "service_id": self.service_id,
            "public_id": self.public_id,
            "name": self.name,
            "duration_minutes": self.duration_minutes,
            "price": str(self.price),
        }


@dataclass(frozen=True)
class ExtraServices:
    """Los servicios extra elegidos, en el orden en que se eligieron."""

    lines: tuple[ExtraServiceLine, ...] = ()

    @property
    def amount(self) -> Decimal:
        """Suma de sus precios de lista, SIN descuento."""
        return _money(sum((line.price for line in self.lines), Decimal("0")))

    @property
    def duration_minutes(self) -> int:
        return sum(line.duration_minutes for line in self.lines)

    def snapshot(self) -> list[dict[str, str | int]] | None:
        """Lo que congela el turno; ``None`` sin extras (turno de siempre)."""
        return [line.snapshot() for line in self.lines] or None


NO_EXTRA_SERVICES = ExtraServices()


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def price_extra_services(services: Iterable[CatalogService]) -> ExtraServices:
    """Congela los extras con su precio y su duracion de HOY."""
    return ExtraServices(
        tuple(
            ExtraServiceLine(
                service_id=str(service.id),
                public_id=str(service.public_id),
                name=str(service.name),
                duration_minutes=int(service.duration_minutes),
                price=_money(Decimal(str(service.price or 0))),
            )
            for service in services
        )
    )


def has_duplicates(principal_public_id: str, extra_public_ids: Sequence[str]) -> bool:
    """Un extra repetido, o el principal elegido otra vez como extra."""
    ids = [principal_public_id, *extra_public_ids]
    return len(set(ids)) != len(ids)


def too_many_services(extra_public_ids: Sequence[str]) -> bool:
    return len(extra_public_ids) > MAX_EXTRA_SERVICES


def too_long(total_minutes: int) -> bool:
    return total_minutes > MAX_TOTAL_DURATION_MINUTES


def cache_segment(principal_public_id: str, extra_public_ids: Sequence[str]) -> str:
    """Segmento del servicio en la clave de cache de la disponibilidad.

    Sin extras es el id del principal, igual que siempre (la clave de un turno
    de un servicio no cambia). Con extras, los ids ordenados y unidos con
    ``+``: la grilla solo depende del conjunto (duracion total, profesionales
    que hacen todos y el servicio mas corto), no del orden.
    """
    if not extra_public_ids:
        return principal_public_id
    return CACHE_SEGMENT_SEPARATOR.join(
        sorted([principal_public_id, *extra_public_ids])
    )


def extra_lines_from_snapshot(snapshot: object) -> list[dict[str, Any]]:
    """Las lineas congeladas, tolerando un snapshot nulo o raro.

    El JSON no lo valida la base: una fila que no sea una lista de dicts se lee
    como "sin extras" en vez de romper una respuesta, un mail o una
    reprogramacion.
    """
    if not isinstance(snapshot, list):
        return []
    return [line for line in snapshot if isinstance(line, dict)]


def _int(value: object) -> int:
    try:
        return max(0, int(str(value)))
    except ValueError:
        return 0


def snapshot_duration(snapshot: object) -> int:
    """Minutos de los extras congelados (0 sin extras)."""
    return sum(
        _int(line.get("duration_minutes", 0))
        for line in extra_lines_from_snapshot(snapshot)
    )


def rescheduled_duration(service: Any, appointment: Any) -> int:
    """Minutos del turno movido: el principal con su duracion de HOY (como
    siempre) mas los extras congelados del turno. La comparten las dos
    reprogramaciones."""
    return int(service.duration_minutes) + snapshot_duration(
        getattr(appointment, "extra_services_snapshot", None)
    )


def snapshot_items(snapshot: object) -> list[tuple[str, str, int]]:
    """``(public_id, name, duration_minutes)`` de cada extra congelado, para
    las respuestas (agenda, busqueda, "Mis turnos", reserva)."""
    return [
        (
            str(line.get("public_id", "")),
            str(line.get("name", "")),
            _int(line.get("duration_minutes", 0)),
        )
        for line in extra_lines_from_snapshot(snapshot)
    ]


def snapshot_price(line: dict[str, Any]) -> Decimal:
    try:
        return _money(Decimal(str(line.get("price", "0"))))
    except ArithmeticError:
        return Decimal("0.00")


def services_label(principal_name: str, snapshot: object) -> str:
    """``Corte + Barba``: el principal y los extras, en el orden elegido.

    Sin extras, el nombre del servicio solo (la etiqueta de siempre).
    """
    names = [principal_name] + [
        str(line.get("name", "")) for line in extra_lines_from_snapshot(snapshot)
    ]
    return LABEL_SEPARATOR.join(name for name in names if name)
