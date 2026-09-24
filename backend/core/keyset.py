"""Cursor opaco para paginar por clave ``(instante, id)`` en orden descendente.

Plan de rendimiento F3-08 (R7-11, 2026-09-24): con ``OFFSET`` la base lee y
descarta todas las filas saltadas en cada pagina (la busqueda de turnos llega
a ~1 M). Con la clave de la ultima fila vista, la pagina siguiente arranca en
el indice justo despues de ella.

El cursor es ``base64url("<instante ISO con zona>|<id>")``: opaco para el
front (no se arma ni se interpreta alla) y validado aca: un cursor roto,
ajeno o con un instante sin zona es 422, nunca 500 ni un filtro raro.
"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from core.utils import ensure_utc_aware
from core.validation import PUBLIC_ID_PATTERN

# Tope del parametro ``after`` (regla 9 en su intencion: todo parametro de la
# API tiene cota). Un cursor real mide ~60 caracteres.
CURSOR_MAX_LENGTH = 200
_ID = re.compile(PUBLIC_ID_PATTERN)


class InvalidCursorError(ValueError):
    """El cursor no es uno que haya emitido la API."""


def encode_cursor(instant: datetime, row_id: str) -> str:
    """Cursor de la fila ``(instant, row_id)``; el instante viaja en UTC."""
    crudo = f"{ensure_utc_aware(instant).isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(crudo.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """``(instante UTC aware, id)`` de un cursor de ``encode_cursor``.

    ``astimezone`` va adentro del ``try``: un instante valido en su zona
    puede desbordar al pasarlo a UTC (``0001-01-01T00:00:00+14:00``) y el
    ``OverflowError`` salia 500 por el handler generico.
    """
    try:
        relleno = "=" * (-len(cursor) % 4)
        crudo = base64.urlsafe_b64decode(cursor + relleno).decode()
        instante_iso, row_id = crudo.split("|", 1)
        instante = datetime.fromisoformat(instante_iso)
        if instante.tzinfo is None or not _ID.fullmatch(row_id):
            raise InvalidCursorError("cursor invalido")
        return instante.astimezone(timezone.utc), row_id
    except (binascii.Error, UnicodeDecodeError, ValueError, OverflowError) as exc:
        raise InvalidCursorError("cursor invalido") from exc


def before_key(
    instant_column: Any, id_column: Any, instant: datetime, row_id: str
) -> ColumnElement[bool]:
    """Filas que van DESPUES de la clave en orden ``(instante, id)`` descendente.

    Es ``(instante, id) < (clave)`` escrito sin comparacion de filas: la cota
    ``instante <= clave`` va sola para que Postgres la use como ``Index Cond``
    del indice que empieza por la tienda y el instante (bajo RLS solo los
    predicados leakproof llegan al indice, y la comparacion de filas no lo
    es); el desempate por ``id`` queda como filtro sobre ese rango.
    """
    return and_(
        instant_column <= instant,
        or_(
            instant_column < instant,
            and_(instant_column == instant, id_column < row_id),
        ),
    )
