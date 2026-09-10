"""Cache de disponibilidad: una sola forma de escribir y de invalidar.

Historia (2026-09-10): la clave que escribia ``AvailabilityService`` tenia
seis segmentos (incluia ``force_all`` y ``hide_private_reasons``) y todas las
invalidaciones usaban cuatro; ademas ``cancel`` y ``release`` borraban con un
asterisco literal que Redis no interpreta. Ninguna invalidacion coincidia con
ninguna clave: al bloquear, cancelar o liberar, la pagina publica mostraba el
estado viejo hasta que vencia el TTL de cinco minutos.

Ahora la clave lleva un NUMERO DE VERSION por (tienda, fecha local). Invalidar
es incrementar ese numero con una sola llamada (``INCR``) y cubre todos los
servicios y todas las variantes de flags de ese dia; no hace falta enumerar
claves ni usar comodines. Leer cuesta un ``GET`` extra por consulta.

La fecha es la LOCAL de Argentina: la disponibilidad se consulta por dia
local, y un turno de 22:00 cae en el dia UTC siguiente. Se invalida el dia
local del turno y, por si acaso, el dia UTC cuando difiere.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from collections.abc import Awaitable
from typing import Any, Protocol, runtime_checkable

from core.utils import ARGENTINA_TZ

SLOTS_TTL_SECONDS = 300


@runtime_checkable
class AvailabilityCacheClient(Protocol):
    """Lo minimo que se necesita de Redis (o de un doble en tests).

    Parametros posicionales y retornos ``Awaitable`` para que tanto
    ``redis.asyncio.Redis`` (``name``/``time``) como el ``MockRedis`` de los
    tests (``key``/``seconds``) satisfagan el protocolo sin adaptadores.
    """

    def get(self, key: str, /) -> Awaitable[Any]: ...

    def setex(self, key: str, seconds: int, value: str, /) -> Awaitable[Any]: ...

    def incr(self, key: str, /) -> Awaitable[int]: ...


def version_key(store_id: str, day: date) -> str:
    return f"availability:v:{store_id}:{day.isoformat()}"


async def current_version(
    client: AvailabilityCacheClient, store_id: str, day: date
) -> str:
    raw = await client.get(version_key(store_id, day))
    if raw is None:
        return "0"
    return raw.decode() if isinstance(raw, bytes) else str(raw)


def slots_key(
    store_id: str,
    day: date,
    version: str,
    service_public_id: str,
    *,
    force_all: bool,
    hide_private_reasons: bool,
) -> str:
    return (
        f"availability:{store_id}:{day.isoformat()}:v{version}:"
        f"{service_public_id}:{int(force_all)}:{int(hide_private_reasons)}"
    )


def local_days_touched(*instants: datetime) -> set[date]:
    """Dias (locales y UTC) que un conjunto de instantes puede afectar."""
    days: set[date] = set()
    for instant in instants:
        aware = instant if instant.tzinfo else instant.replace(tzinfo=timezone.utc)
        days.add(aware.astimezone(ARGENTINA_TZ).date())
        days.add(aware.astimezone(timezone.utc).date())
    return days


async def invalidate_availability(
    client: AvailabilityCacheClient, store_id: str, *instants: datetime
) -> None:
    """Invalida la disponibilidad de la tienda para los dias que tocan los instantes.

    Llamar en TODO camino que cambie la agenda: reservar, cancelar, liberar,
    reprogramar (ambas fechas), expirar una sena, y crear/editar/borrar
    bloqueos. Nunca falla la operacion de negocio por un Redis caido: el
    llamador decide si envuelve en try/except; aca solo se hace el INCR.
    """
    for day in local_days_touched(*instants):
        await client.incr(version_key(store_id, day))


async def invalidate_availability_range(
    client: AvailabilityCacheClient,
    store_id: str,
    starts_at: datetime,
    ends_at: datetime,
) -> None:
    """Como ``invalidate_availability`` pero para cada dia local de un rango (bloqueos)."""
    start_local = (
        starts_at if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc)
    ).astimezone(ARGENTINA_TZ)
    end_local = (
        ends_at if ends_at.tzinfo else ends_at.replace(tzinfo=timezone.utc)
    ).astimezone(ARGENTINA_TZ)
    day = start_local.date()
    last = end_local.date()
    seen: set[date] = set()
    while day <= last:
        seen.add(day)
        day = date.fromordinal(day.toordinal() + 1)
    seen |= local_days_touched(starts_at, ends_at)
    for touched in seen:
        await client.incr(version_key(store_id, touched))
