from datetime import date as _date, datetime, time as _time, timedelta, timezone
from zoneinfo import ZoneInfo

# Shifty opera solo en Argentina. Los horarios que carga una tienda ("abro
# 09:00") son hora local; la base guarda todo en UTC. Sin esta conversion, un
# negocio que abre 09:00 terminaba aceptando reservas a las 09:00 UTC, o sea
# 06:00 de la manana hora argentina.
ARGENTINA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

# Horizonte del portal en dias locales desde hoy (F1-11, decision 14 del
# dueno). Acota SOLO la grilla de disponibilidad sin token
# (``/public/availability`` y la rama anonima de ``/appointments/availability``)
# y el inicio de la ventana al anotarse en la lista de espera. No acota
# reservas ni reprogramaciones.
BOOKING_HORIZON_DAYS = 120

# Tope contra el desborde de TODA reserva y reprogramacion (portal, panel,
# alta para un cliente, lista de espera; revision de perf/f4-back,
# 2026-09-25): corta 9999-12-31 sin tocar el producto. Hacia atras, los
# caminos de la tienda (que puede cargar un horario que ya paso) usan el
# mismo valor como piso.
MAX_BOOKING_AHEAD = timedelta(days=730)


def local_to_utc(day: _date, moment: _time) -> datetime:
    """Combina fecha y hora locales de Argentina y devuelve el instante en UTC."""
    return datetime.combine(day, moment, tzinfo=ARGENTINA_TZ).astimezone(timezone.utc)


def now_utc() -> datetime:
    """Devuelve el datetime actual garantizando que sea UTC aware."""
    return datetime.now(timezone.utc)


def today_local() -> _date:
    """El dia de negocio de hoy: la fecha en hora argentina, no la fecha UTC.

    Entre las 21:00 y las 24:00 hora local el dia UTC ya es "manana"; para el
    panel y los reportes "hoy" es lo que dice el calendario del negocio.
    """
    return now_utc().astimezone(ARGENTINA_TZ).date()


def local_day_start(day: _date) -> datetime:
    """Medianoche argentina de ``day`` como instante UTC.

    Es el corte de "un dia" de negocio (regla 24): el dia siguiente se obtiene
    con aritmetica de calendario (``day + timedelta(days=1)``) y se vuelve a
    pasar por aca, nunca sumando ``timedelta(hours=24)`` a un instante.
    """
    return local_to_utc(day, _time.min)


def within_booking_horizon(value: datetime) -> bool:
    """El dia LOCAL de ``value`` no pasa de hoy + ``BOOKING_HORIZON_DAYS``.

    Hoy la usa solo el inicio de la ventana de la lista de espera; la grilla
    publica aplica el mismo horizonte por dia (``require_public_availability_day``).
    Reservar y reprogramar NO se acotan con esto sino con ``within_max_ahead``
    y ``MAX_BOOKING_AHEAD``. Una fecha que ni se puede llevar a hora local
    (anio 9999 con offset) queda afuera en vez de levantar ``OverflowError``
    (500). Sin offset se toma UTC (regla 24).
    """
    try:
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(ARGENTINA_TZ).date() <= today_local() + timedelta(
            days=BOOKING_HORIZON_DAYS
        )
    except OverflowError:
        return False


def within_max_ahead(value: datetime, max_ahead: timedelta) -> bool:
    """``value`` no pasa de ahora + ``max_ahead``.

    La cota contra el desborde de toda reserva y reprogramacion, con
    ``MAX_BOOKING_AHEAD`` (2 anios). No es un horizonte de producto: al
    cliente lo acota la grilla (``BOOKING_HORIZON_DAYS``)."""
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware <= now_utc() + max_ahead


def ensure_utc_aware(value: datetime) -> datetime:
    """SQLite devuelve naive aun con DateTime(timezone=True); Postgres, aware.

    Todo lo que la base guarda es UTC: un naive se interpreta como UTC.
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
