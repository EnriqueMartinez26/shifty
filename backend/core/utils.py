from datetime import date as _date, datetime, time as _time, timezone
from zoneinfo import ZoneInfo

# Shifty opera solo en Argentina. Los horarios que carga una tienda ("abro
# 09:00") son hora local; la base guarda todo en UTC. Sin esta conversion, un
# negocio que abre 09:00 terminaba aceptando reservas a las 09:00 UTC, o sea
# 06:00 de la manana hora argentina.
ARGENTINA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


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


def to_utc_naive(dt: datetime) -> datetime:
    """Convierte un datetime a UTC y le quita la info de timezone (para DBs antiguas o legacy)."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def ensure_utc_aware(value: datetime) -> datetime:
    """SQLite devuelve naive aun con DateTime(timezone=True); Postgres, aware.

    Todo lo que la base guarda es UTC: un naive se interpreta como UTC.
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
