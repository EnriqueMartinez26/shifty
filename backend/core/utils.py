from datetime import datetime, timezone


def now_utc() -> datetime:
    """Devuelve el datetime actual garantizando que sea UTC aware."""
    return datetime.now(timezone.utc)


def to_utc_naive(dt: datetime) -> datetime:
    """Convierte un datetime a UTC y le quita la info de timezone (para DBs antiguas o legacy)."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
