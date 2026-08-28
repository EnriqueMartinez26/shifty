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


def to_utc_naive(dt: datetime) -> datetime:
    """Convierte un datetime a UTC y le quita la info de timezone (para DBs antiguas o legacy)."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
