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

Ademas la clave lleva una GENERACION por tienda (B6-08, 2026-09-19): editar o
borrar un servicio cambia la disponibilidad de todos los dias, y la version
por dia no alcanza (la disponibilidad publica acepta cualquier fecha). Un
solo ``INCR`` de la generacion invalida la tienda entera; la version por dia
sigue siendo la invalidacion de turnos y bloqueos.

La fecha es la LOCAL de Argentina: la disponibilidad se consulta por dia
local, y un turno de 22:00 cae en el dia UTC siguiente. Se invalida el dia
local del turno y, por si acaso, el dia UTC cuando difiere.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from collections.abc import Awaitable, Iterable
from typing import Any, Protocol, runtime_checkable

import structlog

from core.observability import report_exception
from core.redis import REDIS_UNAVAILABLE_ERRORS
from core.utils import ARGENTINA_TZ

logger = structlog.get_logger()

SLOTS_TTL_SECONDS = 300

# Vencimiento de la clave de version. `INCR` sobre una clave que no existe la
# crea SIN TTL, asi que sin esto quedaba una clave por tienda y por dia tocado
# (local y UTC) para siempre, en el mismo Redis que sostiene el rate limit y la
# idempotencia de cobros (B7-09).
#
# Lo que hace seguro vencerla: el TTL se estira en CADA INCR y en CADA lectura
# (`current_version` usa GETEX). Como toda escritura de slots viene despues de
# leer la version en la misma consulta (`AvailabilityService`), al escribir un
# slot la version tiene por delante los siete dias enteros y el slot solo 300 s:
# la version no puede vencer mientras quede vivo un slot escrito bajo ella, y
# un INCR que la recree desde 1 no encuentra slots de "1" que resucitar. Con la
# renovacion solo en INCR eso no se cumplia (rechazo V-diff, 2026-09-18).
VERSION_TTL_SECONDS = 7 * 24 * 60 * 60


@runtime_checkable
class AvailabilityCacheClient(Protocol):
    """Lo minimo que se necesita de Redis (o de un doble en tests).

    Parametros posicionales y retornos ``Awaitable`` para que tanto
    ``redis.asyncio.Redis`` (``name``/``time``) como el ``MockRedis`` de los
    tests (``key``/``seconds``) satisfagan el protocolo sin adaptadores.
    """

    def get(self, key: str, /) -> Awaitable[Any]: ...

    # GETEX (Redis >= 6.2; el compose usa redis:7): lee y estira el TTL en una
    # sola operacion atomica.
    def getex(self, key: str, /, *, ex: int) -> Awaitable[Any]: ...

    def setex(self, key: str, seconds: int, value: str, /) -> Awaitable[Any]: ...

    def incr(self, key: str, /) -> Awaitable[int]: ...

    def expire(self, key: str, seconds: int, /) -> Awaitable[Any]: ...


def version_key(store_id: str, day: date) -> str:
    return f"availability:v:{store_id}:{day.isoformat()}"


async def _bump_version(
    client: AvailabilityCacheClient, store_id: str, day: date
) -> None:
    """Sube la version de un dia y le (re)pone vencimiento.

    Sigue siendo un `INCR`: no se borra ninguna clave ni se usan comodines.
    El `EXPIRE` va despues de CADA `INCR`, asi que un dia que se sigue tocando
    nunca vence; si el proceso se muere entre los dos, la clave queda como
    quedaba antes de B7-09 (sin TTL) y el proximo INCR la arregla.
    """
    key = version_key(store_id, day)
    await client.incr(key)
    await client.expire(key, VERSION_TTL_SECONDS)


async def current_version(
    client: AvailabilityCacheClient, store_id: str, day: date
) -> str:
    """Version vigente del dia, estirando su vencimiento al leerla.

    El GETEX es lo que impide el reciclado: ver `VERSION_TTL_SECONDS`. Si la
    clave no existe no la crea (la version es "0" hasta el primer INCR).
    """
    raw = await client.getex(version_key(store_id, day), ex=VERSION_TTL_SECONDS)
    if raw is None:
        return "0"
    return raw.decode() if isinstance(raw, bytes) else str(raw)


def store_generation_key(store_id: str) -> str:
    return f"availability:g:{store_id}"


async def current_store_generation(
    client: AvailabilityCacheClient, store_id: str
) -> str:
    """Generacion vigente de la tienda, estirando su vencimiento al leerla.

    Mismas reglas que ``current_version`` (B7-09): el GETEX impide que la
    generacion venza y se recicle bajo un slot vivo; si no existe es "0".
    """
    raw = await client.getex(store_generation_key(store_id), ex=VERSION_TTL_SECONDS)
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
    generation: str = "0",
) -> str:
    """Clave de los slots. En produccion se arma con ``resolve_slots_key``.

    ``generation`` tiene default "0" (el valor de una tienda nunca
    invalidada) solo para que los tests que arman claves a mano sigan
    compilando; un llamador nuevo usa ``resolve_slots_key`` y no puede
    olvidarse de la generacion.
    """
    return (
        f"availability:{store_id}:{day.isoformat()}:g{generation}:v{version}:"
        f"{service_public_id}:{int(force_all)}:{int(hide_private_reasons)}"
    )


async def resolve_slots_key(
    client: AvailabilityCacheClient,
    store_id: str,
    day: date,
    service_public_id: str,
    *,
    force_all: bool,
    hide_private_reasons: bool,
) -> str:
    """Lee generacion de la tienda y version del dia y arma la clave vigente."""
    generation = await current_store_generation(client, store_id)
    version = await current_version(client, store_id, day)
    return slots_key(
        store_id,
        day,
        version,
        service_public_id,
        force_all=force_all,
        hide_private_reasons=hide_private_reasons,
        generation=generation,
    )


def local_days_touched(*instants: datetime) -> set[date]:
    """Dias (locales y UTC) que un conjunto de instantes puede afectar."""
    days: set[date] = set()
    for instant in instants:
        aware = instant if instant.tzinfo else instant.replace(tzinfo=timezone.utc)
        days.add(aware.astimezone(ARGENTINA_TZ).date())
        days.add(aware.astimezone(timezone.utc).date())
    return days


def _tolerar_redis_caido(operacion: str, store_id: str, exc: Exception) -> None:
    """Invalidar es best-effort, pero no es silencio (AUD2-B7-03, 2026-09-20).

    El peor efecto de no invalidar es que la disponibilidad publica muestre el
    estado viejo hasta que venza el TTL de cinco minutos. El peor efecto de
    levantar aca es un 500 sobre una reserva YA commiteada, antes del link de
    pago y del mail: una reserva fantasma, sin cobro ni aviso. Entre los dos,
    se sigue; queda el log con la tienda y el evento en Sentry.
    """
    logger.warning(
        "availability_cache_invalidation_failed",
        operacion=operacion,
        store_id=store_id,
        error_type=type(exc).__name__,
        error=str(exc),
        exc_info=True,
    )
    report_exception(exc, operacion=operacion, store_id=store_id)


async def _bump_days(
    client: AvailabilityCacheClient,
    store_id: str,
    days: Iterable[date],
    *,
    operacion: str,
) -> None:
    """Sube la version de cada dia; un Redis caido no corta la operacion."""
    try:
        for day in days:
            await _bump_version(client, store_id, day)
    except REDIS_UNAVAILABLE_ERRORS as exc:
        _tolerar_redis_caido(operacion, store_id, exc)


async def invalidate_availability(
    client: AvailabilityCacheClient, store_id: str, *instants: datetime
) -> None:
    """Invalida la disponibilidad de la tienda para los dias que tocan los instantes.

    Llamar en TODO camino que cambie la agenda: reservar, cancelar, liberar,
    reprogramar (ambas fechas), expirar una sena, y crear/editar/borrar
    bloqueos. Nunca falla la operacion de negocio por un Redis caido: la
    tolerancia vive ACA, no en cada llamador, asi que un camino nuevo nace
    cubierto (AUD2-B7-03). Solo se traga el Redis caido: cualquier otro error
    sube, para que esto no se vuelva un silenciador de bugs.
    """
    await _bump_days(
        client,
        store_id,
        local_days_touched(*instants),
        operacion="invalidate_availability",
    )


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
    await _bump_days(client, store_id, seen, operacion="invalidate_availability_range")


async def invalidate_store_availability(
    client: AvailabilityCacheClient, store_id: str
) -> None:
    """Invalida la disponibilidad de TODOS los dias de la tienda (B6-08).

    Para cambios que no tienen un instante: editar o borrar un servicio. Un
    ``INCR`` de la generacion + ``EXPIRE`` (como ``_bump_version``); no se
    borra ninguna clave ni se usan comodines. Igual que
    ``invalidate_availability``, un Redis caido no corta la operacion.
    """
    key = store_generation_key(store_id)
    try:
        await client.incr(key)
        await client.expire(key, VERSION_TTL_SECONDS)
    except REDIS_UNAVAILABLE_ERRORS as exc:
        _tolerar_redis_caido("invalidate_store_availability", store_id, exc)
